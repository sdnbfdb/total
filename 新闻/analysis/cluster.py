# -*- coding: utf-8 -*-
"""
M2 · 去重 + 增量归簇 + 相关事件（构建文档 §7.3）
第一阶段：日级去重（同天近似标题合并，计次保留）。
第二阶段：按时间序增量归簇（与事件代表成员比对），event_id 锚定首条记录。
入簇加三道门控：代表成员实体交集、簇活跃期、簇规模上限，阻断同域新闻链式合并。
"""
import hashlib
from datetime import date
import numpy as np

from similarity import (T_DUP, T_SAME, T_REL, T_ENTITY_REL,
                        band, combine, entity_jaccard)

SEM_STRICT = 0.82       # 无实体重叠时的直入高分线（阻断同域新闻链式合并）
MAX_INACTIVE_DAYS = 21  # 距该簇最近一次报道超过此天数则不再入簇（防止主题簇长期吞并）
MAX_CLUSTER_SIZE = 40   # 单簇成员上限，超出后新报道另起事件
REP_WINDOW = 12         # 代表成员滑动窗口（只保留最近 12 个）
TOP_CAND = 20           # 事件级建边时每个事件考察的最高相似候选数


def _norm_rows(mat):
    mat = np.asarray(mat, dtype=np.float32)
    n = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.clip(n, 1e-9, None)


def make_event_id(rec):
    """event_id = 首次出现日期 + 首条记录标题哈希（8 位，降低 4 位哈希的碰撞率）。"""
    d = rec["date"].replace("-", "")
    h = hashlib.md5(f"{rec['source']}|{rec['title']}".encode("utf-8")).hexdigest()[:8]
    return f"evt_{d}_{h}"


def day_dedup(records):
    """同天内 combined ≥ T_DUP 或标题完全相同 → 合并为一条（occurrences 累计）。"""
    by_day = {}
    for r in records:
        by_day.setdefault(r["date"], []).append(r)
    out = []
    for day in sorted(by_day):
        rs = by_day[day]
        vecs = _norm_rows(np.stack([r["vec"] for r in rs]))
        sims = vecs @ vecs.T
        kept = []
        for i, r in enumerate(rs):
            merged = False
            for j in kept:
                same_title = rs[j]["title"] == r["title"]
                if same_title or sims[i, j] >= T_DUP:
                    rs[j]["occurrences"] += 1
                    rs[j].setdefault("dup_titles", [])
                    if not same_title:
                        rs[j]["dup_titles"].append(r["title"])
                    rs[j]["ents"] |= r["ents"]
                    merged = True
                    break
            if not merged:
                r.setdefault("occurrences", 1)
                r.setdefault("dup_titles", [])
                kept.append(i)
        out.extend(rs[i] for i in kept)
    return out


def incremental_cluster(records):
    """
    增量归簇：新记录与事件质心粗排、与最近代表成员精排——
    ≥T_SAME 且通过门控则入簇；[T_REL, T_SAME) 记相关关系；<T_REL 新建事件。
    返回 (events, relation_pairs)。
    """
    records = sorted(records, key=lambda r: (r["date"], r["source"] or "", r["title"]))
    events = []
    rel_pairs = {}

    dim = len(records[0]["vec"]) if records else 0
    csum = np.zeros((0, dim), np.float32)   # 事件向量和（质心粗排）
    reps_list = []                          # 每事件最近 ≤REP_WINDOW 个代表成员向量
    reps_ents = []                          # 对应实体集（门控用，避免用簇实体并集）

    for r in records:
        rvec = _norm_rows(r["vec"][None, :])[0]
        rents = set(r["ents"])
        placed = False
        if len(csum):
            cents = csum / np.clip(np.linalg.norm(csum, axis=1, keepdims=True), 1e-9, None)
            sems = cents @ rvec
            order = np.argsort(-sems)[:5]
            best_rel = None
            for idx in order:
                m = float((reps_list[idx] @ rvec).max())
                # 与「代表成员」而非簇实体并集求交集，防止巨型簇门控失效
                ej = max((entity_jaccard(rents, re) for re in reps_ents[idx]), default=0.0)
                s = combine(m, ej)
                b = band(s)
                if b in ("dup", "same"):
                    ev = events[idx]
                    gap_days = (date.fromisoformat(r["date"]) - date.fromisoformat(ev["last_seen"])).days
                    fresh = gap_days <= MAX_INACTIVE_DAYS
                    small = len(ev["records"]) < MAX_CLUSTER_SIZE
                    if b == "dup" or ((ej > 0 or m >= SEM_STRICT) and fresh and small):
                        ev["records"].append(r)
                        ev["last_seen"] = r["date"]
                        ev["ents"] |= rents
                        csum[idx] += rvec
                        reps_list[idx] = np.vstack([reps_list[idx], rvec[None, :]])[-REP_WINDOW:]
                        reps_ents[idx].append(rents)
                        if len(reps_ents[idx]) > REP_WINDOW:
                            reps_ents[idx].pop(0)
                        placed = True
                        break
                if b == "related" and (best_rel is None or s > best_rel[0]):
                    best_rel = (s, idx)
            if not placed and best_rel is not None:
                s, idx = best_rel
                key = frozenset((events[idx]["event_id"], make_event_id(r)))
                rel_pairs[key] = max(rel_pairs.get(key, 0.0), s)
        if not placed:
            ev = {
                "event_id": make_event_id(r),
                "name": r["title"],
                "first_seen": r["date"],
                "last_seen": r["date"],
                "records": [r],
                "ents": set(rents),
            }
            events.append(ev)
            csum = np.vstack([csum, rvec[None, :]])
            reps_list.append(rvec[None, :])
            reps_ents.append([rents])

    # 事件级相关补全：质心粗排取 top 候选 + 语义/实体双通道建边
    if len(events) >= 2:
        cents = csum / np.clip(np.linalg.norm(csum, axis=1, keepdims=True), 1e-9, None)
        ents_sets = [set(e["ents"]) for e in events]
        n = len(events)
        block = 2000
        for i0 in range(0, n, block):
            sims = cents[i0:i0 + block] @ cents.T
            for ii in range(sims.shape[0]):
                i = i0 + ii
                row = sims[ii].copy()
                row[i] = -1.0
                k = min(TOP_CAND, row.size - 1)
                if k < 1 or row.max() < T_ENTITY_REL:
                    continue
                cand = np.argpartition(-row, k)[:k]
                for jj in cand:
                    j = int(jj)
                    if j == i or row[j] < T_ENTITY_REL:
                        continue
                    # 语义带内直接建边；相似度较低者须共享实体（实体召回通道）
                    if row[j] < T_REL and not (ents_sets[i] & ents_sets[j]):
                        continue
                    key = frozenset((events[i]["event_id"], events[j]["event_id"]))
                    rel_pairs[key] = max(rel_pairs.get(key, 0.0), float(row[j]))

    out = []
    for ev in events:
        recs = sorted(ev["records"], key=lambda r: (r["date"], r["source"] or ""))
        days = sorted({r["date"] for r in recs})
        sources = sorted({r["source"] for r in recs if r["source"]})
        out.append({
            "event_id": ev["event_id"],
            "name": ev["name"],
            "first_seen": recs[0]["date"],
            "last_seen": recs[-1]["date"],
            "count": sum(r.get("occurrences", 1) for r in recs),
            "days": days,
            "records": [{k: v for k, v in r.items() if k not in ("vec", "ents")} for r in recs],
            "sources": sources,
            "source_count": len(sources),
            "ents": sorted(ev["ents"]),
        })
    return out, rel_pairs


def attach_relations(events, rel_pairs, top_k=8):
    """把 relation_pairs 整理成每事件 related 列表（对称、按相似度降序）。"""
    by_id = {e["event_id"]: e for e in events}
    rel_map = {e["event_id"]: [] for e in events}
    for key, sim in rel_pairs.items():
        a, b = tuple(key)
        if a not in by_id or b not in by_id:
            continue
        rel_map[a].append({"event_id": b, "name": by_id[b]["name"], "count": by_id[b]["count"],
                           "similarity": round(sim, 3)})
        rel_map[b].append({"event_id": a, "name": by_id[a]["name"], "count": by_id[a]["count"],
                           "similarity": round(sim, 3)})
    for e in events:
        seen = set()
        rels = []
        for r in sorted(rel_map[e["event_id"]], key=lambda x: -x["similarity"]):
            if r["event_id"] in seen:
                continue
            seen.add(r["event_id"])
            rels.append(r)
            if len(rels) >= top_k:
                break
        e["related"] = rels
    return events
