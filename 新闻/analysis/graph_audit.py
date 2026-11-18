# -*- coding: utf-8 -*-
"""
图谱质量体检（统一口径，用于修复前后对比）
用法：
  python analysis/graph_audit.py
  python analysis/graph_audit.py --events <events.json> --graph <knowledge_graph.json> --label 修复前
逐行输出 key: value，两次运行可直接 diff。
"""
import argparse
import collections
import datetime
import json
import os
import random
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOP = set("新闻 报道 回应 引发 曝光 关注 网友 最新 今日 发生 相关 通报 正式 宣布 开始 进行 一个 这个 什么 如何 为何 是否 可以 已经 将会 这些 那些 目前 记者 消息 事件 情况 问题 表示 认为 出现 成为 持续 再次 首次 突然 全网 热搜 话题 视频 图片 直播 将于 推出 上市 官宣 售价 元起".split())

try:
    import jieba
    jieba.setLogLevel(60)

    def toks(s):
        return {w for w in jieba.cut(s or "")
                if len(w) >= 2 and w not in STOP and not re.match(r"^[\d\W_]+$", w)}
except ImportError:
    def toks(s):
        s = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", s or "")
        return {s[i:i + 2] for i in range(len(s) - 1)}


def pct(a, b):
    return 0.0 if not b else round(100.0 * a / b, 1)


def audit(events_path, graph_path, label):
    ev = json.load(open(events_path, encoding="utf-8"))
    kg = json.load(open(graph_path, encoding="utf-8"))
    all_events = ev["events"]
    E = {e["event_id"]: e for e in all_events}
    rel = [x for x in kg["edges"] if x["type"] == "related"]
    fol = [x for x in kg["edges"] if x["type"] == "follows"]
    chains = kg["chains"]
    pairs = {frozenset((x["source"], x["target"])) for x in rel}
    adj = collections.defaultdict(set)
    for x in kg["edges"]:
        adj[x["source"]].add(x["target"])
        adj[x["target"]].add(x["source"])

    print(f"# {label}")
    print(f"generated_at      : {ev.get('generated_at')}")
    print(f"meta              : {json.dumps(ev.get('meta', {}), ensure_ascii=False)}")
    print(f"规模              : 事件 {len(all_events)} / 节点 {kg['stats']['nodes']} / "
          f"相关边 {len(rel)} / 演进边 {len(fol)} / 链 {len(chains)}")
    print(f"重复 event_id     : {len(all_events) - len(E)}")

    # 连通性
    seen, comps = set(), []
    for nid in E:
        if nid in seen:
            continue
        st, c = [nid], []
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x)
            c.append(x)
            st.extend(adj[x] - seen)
        comps.append(c)
    comps.sort(key=len, reverse=True)
    iso = sum(1 for n in kg["nodes"] if not adj[n["id"]])
    chain_nodes = {i for c in chains for i in c}
    two = sum(1 for c in chains if len(c) == 2)
    print(f"连通              : 孤立节点 {pct(iso, len(kg['nodes']))}% / "
          f"最大分量 {pct(len(comps[0]), len(E))}% / "
          f"链覆盖节点 {pct(len(chain_nodes), len(E))}% / "
          f"长度=2的链 {pct(two, len(chains))}%")

    big = max(all_events, key=lambda e: e["count"]) if all_events else None
    if big:
        print(f"最大簇            : count {big['count']} / 独立标题 {len(big['records'])} / {big['name'][:34]}")

    # 召回：同主题 7 日内事件对直接有边
    parts = []
    for kw in ["法国", "特斯拉", "进博会", "普京", "iPhone"]:
        ids = [i for i, e in E.items() if kw.lower() in e["name"].lower()]
        if len(ids) < 3:
            parts.append(f"{kw} 样本少")
            continue
        s = random.Random(42).sample(ids, min(len(ids), 60))
        tot = hit = 0
        for x in range(len(s)):
            for y in range(x + 1, len(s)):
                a, b = s[x], s[y]
                if abs((datetime.date.fromisoformat(E[a]["first_seen"]) -
                        datetime.date.fromisoformat(E[b]["first_seen"])).days) > 7:
                    continue
                tot += 1
                hit += frozenset((a, b)) in pairs
        parts.append(f"{kw} {pct(hit, tot)}%({tot}对)")
    fr = [e for e in all_events if "法国" in e["name"]
          and any(k in e["name"] for k in ["骚乱", "失控", "奢侈品", "市政厅", "0元购", "抗议"])]
    fh = sum(1 for i in range(len(fr)) for j in range(i + 1, len(fr))
             if frozenset((fr[i]["event_id"], fr[j]["event_id"])) in pairs)
    print(f"召回·同主题直接边 : {' / '.join(parts)}")
    print(f"召回·法国骚乱系列 : {len(fr)} 节点 / 两两 {len(fr) * (len(fr) - 1) // 2} 对 / 有边 {fh} 对")

    # 噪声
    no_ent = no_name = both = 0
    for f in fol:
        a, b = f["source"], f["target"]
        ea, eb = set(E[a].get("ents") or []), set(E[b].get("ents") or [])
        na, nb = toks(E[a]["name"]), toks(E[b]["name"])
        e0, n0 = not (ea & eb), not (na & nb)
        no_ent += e0
        no_name += n0
        both += e0 and n0
    print(f"噪声·演进边       : 无共享实体 {pct(no_ent, len(fol))}% / "
          f"名称无共享实词 {pct(no_name, len(fol))}% / 强疑似串错 {pct(both, len(fol))}%")

    longc = [c for c in chains if len(c) >= 3]
    off = hops = drift = 0
    for c in longc:
        base = toks(E[c[0]]["name"])
        o = sum(1 for i in c[1:] if not (base & toks(E[i]["name"])))
        off += o
        hops += len(c) - 1
        drift += o / (len(c) - 1) >= 0.5
    print(f"噪声·链内漂移     : 长链 {len(longc)} 条 / 后续节点跑偏 {pct(off, hops)}% / "
          f"过半跑偏的链 {pct(drift, len(longc))}%")

    tot = zero = 0
    for i in chain_nodes:
        if i not in E:
            continue
        a = toks(E[i]["name"])
        for r in E[i]["records"]:
            tot += 1
            zero += not (a & toks(r["title"]))
    print(f"噪声·簇内新闻     : 链上 {tot} 条独立标题 / 与事件名零共享实词 {pct(zero, tot)}%")

    cat = collections.Counter(e.get("category") for e in all_events)
    phase = collections.Counter(e.get("phase") for e in all_events)
    print(f"分布              : 其他类 {pct(cat['其他'], len(all_events))}% / "
          f"平息 {pct(phase['平息'], len(all_events))}%")
    print()


def main():
    ap = argparse.ArgumentParser(description="图谱质量体检")
    ap.add_argument("--events", default=os.path.join(BASE_DIR, "data", "events.json"))
    ap.add_argument("--graph", default=os.path.join(BASE_DIR, "data", "knowledge_graph.json"))
    ap.add_argument("--label", default="当前图谱")
    args = ap.parse_args()
    audit(args.events, args.graph, args.label)


if __name__ == "__main__":
    main()
