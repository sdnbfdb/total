# -*- coding: utf-8 -*-
"""
入口 · 一键跑通全流程（构建文档 §5.1/§10）
用法：
  python analysis/analyze.py                 # 全量：解析→特征→归簇→标注→报告
  python analysis/analyze.py --backfill-content 200   # 正文回抓（M2b）
  python analysis/analyze.py --no-report     # 只更新事件库
事件归簇为「增量归簇」算法 + event_id 锚定首条记录，全量重跑即增量（幂等，ID 稳定）。
"""
import os
import sys
import time
import random
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np

import parse_snapshots
import vectorize
import similarity
import cluster
import tdt
import phase as phase_mod
import classify as classify_mod
import timeline as timeline_mod
import store
import report
import content
from llm_narrate import narrate

EVAL_SEEDS = [
    ("法国爆发近年来最严重暴力骚乱", "法国失控了", "同事件"),
    ("法国爆发近年来最严重暴力骚乱", "法国多地奢侈品门店被洗劫一空", "同事件"),
    ("法国爆发近年来最严重暴力骚乱", "法国人开始在奢侈品店0元购", "同事件"),
    ("土豆价格今年持续走高", "马铃薯价格再度攀升 多地货源紧张", "同事件"),
    ("红薯价格大涨 农户扩种", "地瓜产地收购价创新高", "同事件"),
    ("红富士苹果价格再度上涨", "苹果手机新机型发布销量火爆", "无关"),
    ("土地管理法修订草案公布", "红薯丰收农民增收", "无关"),
    ("土豆主产区迎来丰收", "地瓜干加工订单翻倍", "相关"),
    ("中国60岁以上人口超3.23亿", "成都大学生：2000元左右生活费是主流", "无关"),
    ("周末打虎！黄日波被查", "法国爆发近年来最严重暴力骚乱", "无关"),
]


def _attach_vecs_and_ents(records):
    """为记录挂语义向量 vec / 实体集 ents；语义通道不可用时直接抛错，不降级。"""
    texts = [vectorize.embed_text(r) for r in records]
    emb = vectorize.Embedder()
    cache = vectorize.VecCache()
    out = [None] * len(records)
    miss_idx = []
    for i, r in enumerate(records):
        v = cache.get_vec_or_none(r)
        if v is None:
            miss_idx.append(i)
        else:
            out[i] = v
    if miss_idx:
        print(f"  [vectorize] 语义编码 {len(miss_idx)} 条（缓存命中 {len(records) - len(miss_idx)}）…")
        mat = emb.encode([texts[i] for i in miss_idx])
        cache.put([records[i] for i in miss_idx], mat)
        for k, i in enumerate(miss_idx):
            out[i] = mat[k]
    for i, r in enumerate(records):
        r["vec"] = out[i].astype(np.float32)
        r["ents"] = vectorize.entities((r["title"] or "") + " " + (r.get("snippet") or ""))
    return len(miss_idx)


def _enrich(events, observed_days, use_llm):
    for ev in events:
        ev["bursts"] = tdt.detect_bursts(ev, observed_days)
        ev["phase"] = phase_mod.judge_phase(ev, observed_days, ev["bursts"])
        ev["category"] = classify_mod.classify(ev)
        ev["timeline"] = timeline_mod.build_timeline(ev)
        ev["summary"] = tdt.timeline_summary(ev, ev["bursts"])
        if use_llm:
            ev["summary"] = narrate(ev, ev["summary"])
        pool = content.body_pool(ev)
        if pool:
            ev["body_pool"] = pool[:8]
    return events


def _build_eval_pairs(events, records, target=200):
    """§11 回归集：种子难例 + 簇内难正例 + 相关对 + 无关对，自动预标待人工校对。"""
    random.seed(42)
    pairs = []

    def add(a, b, label, note):
        pairs.append({"id": f"p{len(pairs) + 1:03d}", "a": a, "b": b,
                      "prelabel": label, "label": "", "status": "auto_prelabel", "note": note})

    for a, b, lab in EVAL_SEEDS:
        add(a, b, lab, "seed")

    vec_map = {}
    for r in records:
        vec_map[vectorize.VecCache.rec_key(r)] = r["vec"]

    def sem(a, b):
        v1 = vec_map[vectorize.VecCache.rec_key(a)]
        v2 = vec_map[vectorize.VecCache.rec_key(b)]
        return float(v1 @ v2 / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9))

    big = sorted(events, key=lambda e: -e["count"])[:120]
    # 簇内最难正例：同事件、语义分最低的标题对
    n_intra = n_rel = 0
    for ev in big:
        rs = ev["records"][:6]
        cand = []
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                cand.append((sem(rs[i], rs[j]), rs[i], rs[j]))
        cand.sort(key=lambda x: x[0])
        for s, a, b in cand[:2]:
            if n_intra >= 60:
                break
            add(a["title"], b["title"], "同事件", f"intra|{ev['event_id']}|sim={s:.3f}")
            n_intra += 1
        if n_intra >= 60 and n_rel >= 60:
            break
    # 相关事件对
    for ev in big:
        for rel in ev.get("related", [])[:1]:
            if n_rel >= 60:
                break
            add(ev["name"], rel["name"], "相关", f"related|sim={rel['similarity']}")
            n_rel += 1
        if n_rel >= 60:
            break
    # 无关对：随机低相似度跨事件标题
    all_recs = [r for ev in events for r in ev["records"]]
    while len(pairs) < target:
        a, b = random.sample(all_recs, 2)
        s = sem(a, b)
        if s < 0.30 and a["title"] != b["title"]:
            add(a["title"], b["title"], "无关", f"neg|sim={s:.3f}")
        if len(pairs) > target + 40:
            break
    return pairs[:target]


def run(backfill_limit=None, no_report=False, use_llm=False, verbose=True):
    t0 = time.time()
    if backfill_limit is not None:
        records, calendar, stats = parse_snapshots.parse_all()
        cutoff = calendar["observed"][-30] if len(calendar["observed"]) >= 30 else calendar["observed"][0]
        recent = [r for r in records if r["date"] >= cutoff]
        done = content.backfill(recent, limit=backfill_limit, verbose=True)
        print(f"[content] 回抓完成 {done}（缓存目录 data/articles/）")
        return {"content": done}

    if verbose:
        print("[1/7] 解析快照 …")
    records, calendar, stats = parse_snapshots.parse_all()
    store.save_calendar(calendar)
    if verbose:
        print(f"      {stats['files']} 份快照 / {stats['records']} 条标题记录 / "
              f"观测日 {stats['days']} / 缺日 {len(calendar['missing'])}")

    if verbose:
        print("[2/7] 构建特征（jieba + 实体 + bge 语义向量）…")
    encoded_new = _attach_vecs_and_ents(records)

    if verbose:
        print("[3/7] 日级去重 …")
    deduped = cluster.day_dedup(records)
    if verbose:
        print(f"      {len(records)} → {len(deduped)} 条（合并转载）")

    if verbose:
        print("[4/7] 增量归簇 + 相关事件 …")
    events, rel_pairs = cluster.incremental_cluster(deduped)
    events = cluster.attach_relations(events, rel_pairs)
    if verbose:
        print(f"      事件 {len(events)} 个，相关关系 {len(rel_pairs)} 对")

    if verbose:
        print("[5/7] 突发/阶段/类别/时间线/摘要 …")
    events = _enrich(events, calendar["observed"], use_llm)
    events.sort(key=lambda e: (-e["source_count"], -e["count"]))

    if verbose:
        print("[6/7] 评估回归集 …")
    pairs = _build_eval_pairs(events, deduped)
    store.save_eval_pairs(pairs)

    if verbose:
        print("[7/7] 持久化 + 报告 + 知识图谱 …")
    meta = {
        "thresholds": {"T_DUP": similarity.T_DUP, "T_SAME": similarity.T_SAME,
                       "T_REL": similarity.T_REL},
        "embed_model": vectorize.EMBED_MODEL,
        "embed_dim": vectorize.EMBED_DIM,
        "encoded_new": encoded_new,
        "snapshot_files": stats["files"],
        "records_raw": stats["records"],
        "records_deduped": len(deduped),
    }
    store.save_events(events, meta=meta)
    md_path = html_path = None
    if not no_report:
        md_path, html_path = report.write_reports(events, calendar, stats)
    import knowledge_graph
    kg = knowledge_graph.build_and_save(events)
    kg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "reports", "knowledge_graph.html")

    if verbose:
        print(f"\n✅ 完成（{time.time() - t0:.1f}s）：事件 {len(events)} · 回归集 {len(pairs)} 对")
        if md_path:
            print(f"   报告: {md_path}")
            print(f"         {html_path}")
        print(f"   图谱: {kg_path}")
        print(f"         节点 {kg['stats']['nodes']} · 相关边 {kg['stats']['related_edges']} · "
              f"演进边 {kg['stats']['follows_edges']} · 故事链 {kg['stats']['chains']} 条")
        for ev in events[:5]:
            print(f"   · [{ev['phase']}/{ev['category']}] {ev['name'][:28]} "
                  f"累计{ev['count']}次 {ev['source_count']}源 相关{len(ev.get('related', []))}")
    return {"events": events, "calendar": calendar, "eval_pairs": pairs,
            "report": (md_path, html_path), "graph": kg, "stats": stats}


def incremental(use_llm=False):
    """§12 每日快照后调用：幂等全量重建（event_id 锚定，稳定），并同步刷新当日报告。"""
    return run(no_report=False, use_llm=use_llm, verbose=False)


def encode_only():
    """只重建语义向量缓存（解析 → 全量编码 → 落盘），不跑归簇，供换模型/修缓存后使用。"""
    import time as _time
    t0 = _time.time()
    records, calendar, stats = parse_snapshots.parse_all()
    print(f"[encode] {stats['files']} 份快照 / {stats['records']} 条记录，开始全量语义编码…", flush=True)
    emb = vectorize.Embedder()
    cache = vectorize.VecCache()
    texts = [vectorize.embed_text(r) for r in records]
    uniq = list(dict.fromkeys(texts))          # 同一标题只编码一次
    print(f"[encode] 唯一文本 {len(uniq)} / 记录 {len(texts)}", flush=True)
    mat_uniq = emb.encode(uniq)
    vmap = dict(zip(uniq, mat_uniq))
    mat = np.stack([vmap[t] for t in texts])
    cache.put(records, mat)
    print(f"[encode] 完成（{_time.time() - t0:.1f}s）：唯一 key {len(cache.key_list)} 条 · "
          f"缓存 {cache.vecs.shape} · 模型 {vectorize.MODEL_TAG}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="事件脉络分析系统 v1.4")
    ap.add_argument("--incremental", action="store_true", help="增量更新事件库（幂等重建）")
    ap.add_argument("--backfill-content", type=int, metavar="N", help="回抓 N 篇正文（M2b）")
    ap.add_argument("--no-report", action="store_true", help="不生成报告")
    ap.add_argument("--llm", action="store_true", help="启用 LLM 叙事（需 LLM_API_KEY）")
    ap.add_argument("--encode-only", action="store_true", help="只重建语义向量缓存")
    args = ap.parse_args()
    if args.encode_only:
        encode_only()
    elif args.backfill_content:
        run(backfill_limit=args.backfill_content)
    elif args.incremental:
        incremental(use_llm=args.llm)
    else:
        run(no_report=args.no_report, use_llm=args.llm)


if __name__ == "__main__":
    main()
