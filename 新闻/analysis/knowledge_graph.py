# -*- coding: utf-8 -*-
"""
知识图谱层（2026-11-03 需求）
- 节点 = 事件（含类别/阶段/次数/摘要等属性）
- 「相关」边 = 相关事件（语义灰区关联，无向，权重=相似度）
- 「演进」边 = 顺延节点（相关且时间顺延：后事件在前事件活跃窗口内/之后 7 天内首现），
  有向，构成故事链（演进链）。
输出：data/knowledge_graph.json / .graphml / .cypher ；reports/knowledge_graph.html
"""
import os
import json
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORT_DIR = os.path.join(BASE_DIR, "reports")

FOLLOW_MAX_GAP = 14   # 后事件首现 ≤ 前事件末现 + 14 天
FOLLOW_MIN_GAP = -7   # 允许并行事件有短期活跃重叠
FOLLOW_TOP_K = 2      # 每节点最多 2 条出向演进边（宁缺毋滥）
FOLLOW_MIN_SIM = 0.72 # 无实体重叠时，演进边要求的语义下限（且须名称有词面关联）
MAX_CHAIN_LEN = 20

# 类别基色（与 HTML 端一致）
CAT_COLORS = {
    "时政": "#185fa5", "财经": "#854f0b", "科技": "#534ab7", "体育": "#0f6e56",
    "娱乐": "#993556", "国际": "#a32d2d", "社会民生": "#27500a",
    "健康科普": "#1d9e75", "其他": "#888780",
}


def _shade(hex_color, t):
    """强度 t∈[0,1] → 类别色的深浅：0 最浅（近白），1 最深（压暗）。"""
    base = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    if t < 0.5:
        k = min((0.5 - t) * 1.3, 0.8)          # 向白混合
        rgb = tuple(int(c + (242 - c) * k) for c in base)
    else:
        k = min((t - 0.5) * 0.7, 0.35)          # 向黑压暗
        rgb = tuple(int(c * (1 - k)) for c in base)
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _d(s):
    return datetime.date.fromisoformat(s)


def _ent_jaccard(a, b):
    a, b = set(a or []), set(b or [])
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


def _share_word(a, b):
    """两标题是否共享中文/英文 2-gram（词面关联，过滤纯语义巧合）。"""
    import re

    def grams(t):
        t = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", t or "")
        return {t[i:i + 2] for i in range(len(t) - 1)}
    return bool(grams(a) & grams(b))


def build_graph(events):
    """→ {nodes, edges, chains, stats}"""
    by_id = {e["event_id"]: e for e in events}

    nodes = [{
        "id": e["event_id"],
        "name": e["name"],
        "category": e.get("category", "其他"),
        "phase": e.get("phase", ""),
        "count": e["count"],
        "source_count": e["source_count"],
        "first_seen": e["first_seen"],
        "last_seen": e["last_seen"],
        "summary": e.get("summary", ""),
    } for e in events]

    edges, seen = [], set()
    for e in events:
        for r in e.get("related", []):
            key = frozenset((e["event_id"], r["event_id"]))
            if key in seen or r["event_id"] not in by_id:
                continue
            seen.add(key)
            edges.append({
                "source": e["event_id"], "target": r["event_id"],
                "type": "related", "label": "相关",
                "weight": round(r.get("similarity", 0.5), 3),
            })

    # 演进边：相关对 + 时间顺延（后事件首现在前事件活跃期内或末现后 7 天内，且更晚）
    follows = []
    for ed in edges:
        a, b = by_id[ed["source"]], by_id[ed["target"]]
        if a["first_seen"] == b["first_seen"]:
            continue
        lo, hi = (a, b) if a["first_seen"] < b["first_seen"] else (b, a)
        if not (_d(lo["first_seen"]) < _d(hi["first_seen"])):
            continue
        gap = (_d(hi["first_seen"]) - _d(lo["last_seen"])).days
        if gap > FOLLOW_MAX_GAP or gap < FOLLOW_MIN_GAP:
            continue
        ej = _ent_jaccard(a.get("ents"), b.get("ents"))
        if ej <= 0 and (ed["weight"] < FOLLOW_MIN_SIM
                        or not _share_word(a.get("name", ""), b.get("name", ""))):
            continue  # 无实体重叠：须高语义 + 名称词面关联，否则只是并行相关，不串成链
        w = round(ed["weight"] + 0.08 * ej, 3)
        follows.append({
            "source": lo["event_id"], "target": hi["event_id"],
            "type": "follows", "label": "演进",
            "weight": w, "gap_days": gap,
        })

    # 每节点保留 top-K 出向演进边
    by_src = {}
    for f in sorted(follows, key=lambda x: -x["weight"]):
        lst = by_src.setdefault(f["source"], [])
        if len(lst) < FOLLOW_TOP_K:
            lst.append(f)
    follows = [f for lst in by_src.values() for f in lst]
    edges.extend(follows)

    chains = _build_chains(follows, by_id)

    # 视觉编码（2026-11-03 需求）：
    #   节点大小 ∝ 关联度（相关节点数 + 分支数）
    #   颜色深浅 ∝ 重复次数 × 时间近度（次数越多、出现越近 → 越深）
    import math
    deg = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    latest = max(_d(n["last_seen"]) for n in nodes) if nodes else datetime.date.today()
    max_count = max((n["count"] for n in nodes), default=1) or 1
    for n in nodes:
        n["degree"] = deg.get(n["id"], 0)
        days_ago = (latest - _d(n["last_seen"])).days
        recency = max(0.0, 1.0 - days_ago / 45.0)            # 45 天内算「近」
        cnt = math.log10(n["count"] + 1) / math.log10(max_count + 1)
        n["intensity"] = round(0.45 * cnt + 0.55 * recency, 3)
        n["color"] = _shade(CAT_COLORS.get(n["category"], "#888780"), n["intensity"])

    stats = {
        "nodes": len(nodes),
        "related_edges": sum(1 for e in edges if e["type"] == "related"),
        "follows_edges": len(follows),
        "chains": len(chains),
    }
    return {"nodes": nodes, "edges": edges, "chains": chains, "stats": stats}


def _build_chains(follows, by_id):
    """从演进边贪心串故事链（每节点最多被一条链占用作后继）。"""
    best_succ, in_succ = {}, set()
    for f in sorted(follows, key=lambda x: -x["weight"]):
        if f["source"] not in best_succ and f["target"] not in in_succ:
            best_succ[f["source"]] = f["target"]
            in_succ.add(f["target"])

    chains = []
    used = set()
    order = sorted(by_id, key=lambda i: by_id[i]["first_seen"])
    for start in order:
        if start in used:
            continue
        path = [start]
        used.add(start)
        cur = start
        while cur in best_succ and len(path) < MAX_CHAIN_LEN:
            nxt = best_succ[cur]
            if nxt in used:
                break
            path.append(nxt)
            used.add(nxt)
            cur = nxt
        if len(path) >= 2:
            chains.append(path)

    def chain_weight(p):
        return sum(by_id[i]["count"] * 10 + by_id[i]["source_count"] for i in p)
    chains.sort(key=chain_weight, reverse=True)
    return chains


def _xml_esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def _cy_esc(s):
    return (s or "").replace("\\", "\\\\").replace("'", "\\'")


def save_graphml(g, path):
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '<key id="name" for="node" attr.name="name" attr.type="string"/>',
        '<key id="category" for="node" attr.name="category" attr.type="string"/>',
        '<key id="phase" for="node" attr.name="phase" attr.type="string"/>',
        '<key id="count" for="node" attr.name="count" attr.type="int"/>',
        '<key id="etype" for="edge" attr.name="type" attr.type="string"/>',
        '<key id="weight" for="edge" attr.name="weight" attr.type="double"/>',
        '<graph id="G" edgedefault="directed">',
    ]
    for n in g["nodes"]:
        lines.append(f'<node id="{n["id"]}">'
                     f'<data key="name">{_xml_esc(n["name"])}</data>'
                     f'<data key="category">{_xml_esc(n["category"])}</data>'
                     f'<data key="phase">{_xml_esc(n["phase"])}</data>'
                     f'<data key="count">{n["count"]}</data></node>')
    for i, e in enumerate(g["edges"]):
        d = "directed" if e["type"] == "follows" else "undirected"
        lines.append(f'<edge id="e{i}" source="{e["source"]}" target="{e["target"]}" directed="{d}">'
                     f'<data key="etype">{e["type"]}</data>'
                     f'<data key="weight">{e["weight"]}</data></edge>')
    lines += ['</graph>', '</graphml>']
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def save_cypher(g, path):
    lines = ["// 事件知识图谱 · Neo4j 导入（neo4j-admin database import 或逐条执行）",
             "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE;"]
    for n in g["nodes"]:
        lines.append(
            f"MERGE (e:Event {{id:'{_cy_esc(n['id'])}'}}) SET e.name='{_cy_esc(n['name'])}', "
            f"e.category='{_cy_esc(n['category'])}', e.phase='{_cy_esc(n['phase'])}', "
            f"e.count={n['count']}, e.first_seen=date('{n['first_seen']}'), e.last_seen=date('{n['last_seen']}');")
    for e in g["edges"]:
        if e["type"] == "related":
            lines.append(f"MERGE (a:Event {{id:'{_cy_esc(e['source'])}'}})-[:RELATED {{weight:{e['weight']}}}]->"
                         f"(b:Event {{id:'{_cy_esc(e['target'])}'}});")
        else:
            lines.append(f"MERGE (a:Event {{id:'{_cy_esc(e['source'])}'}})-[:FOLLOWS {{weight:{e['weight']}}}]->"
                         f"(b:Event {{id:'{_cy_esc(e['target'])}'}});")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _viz_subgraph(g, max_nodes=250):
    """取 top 节点（按 影响力）+ 其 1 跳邻居，供 HTML 可视化。"""
    scored = sorted(g["nodes"], key=lambda n: -(n["source_count"] * 10 + n["count"]))
    keep = []
    keep_set = set()
    for n in scored:
        if len(keep) >= max_nodes:
            break
        keep.append(n)
        keep_set.add(n["id"])
    for e in g["edges"]:
        if e["source"] in keep_set and e["target"] in keep_set:
            continue
        if e["source"] in keep_set or e["target"] in keep_set:
            for nid in (e["source"], e["target"]):
                if nid not in keep_set and len(keep) < int(max_nodes * 1.4):
                    node = next((x for x in g["nodes"] if x["id"] == nid), None)
                    if node:
                        keep.append(node)
                        keep_set.add(nid)
    edges = [e for e in g["edges"] if e["source"] in keep_set and e["target"] in keep_set]
    chains = [c for c in g["chains"] if all(i in keep_set for i in c)]
    return {"nodes": keep, "edges": edges, "chains": chains}


def save_html(g, path, max_nodes=250):
    sub = _viz_subgraph(g, max_nodes)
    cats = sorted({n["category"] for n in g["nodes"]})
    data_json = json.dumps(sub, ensure_ascii=False)
    cats_json = json.dumps(cats, ensure_ascii=False)
    chains_html = ""
    by_id = {n["id"]: n for n in sub["nodes"]}
    for ci, chain in enumerate(sub["chains"][:12], 1):
        names = " → ".join(f'{by_id[i]["name"][:16]}' for i in chain if i in by_id)
        chains_html += f'<li><b>链{ci}</b>（{len(chain)} 节点）{names}</li>'
    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>新闻事件知识图谱</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#f6f7f9;color:#1f2937}}
header{{padding:14px 22px 8px}} h1{{font-size:20px;margin:0}}
.sub{{color:#6b7280;font-size:12px;margin:4px 0 0}}
.bar{{padding:6px 22px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}}
button{{border:1px solid #d1d5db;background:#fff;border-radius:8px;padding:5px 12px;cursor:pointer}}
button.on{{background:#185fa5;color:#fff;border-color:#185fa5}}
main{{display:flex;gap:14px;padding:0 22px 22px}}
#chart{{flex:1;height:72vh;background:#fff;border:1px solid #e5e7eb;border-radius:12px}}
#side{{width:320px;background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;overflow:auto;height:72vh}}
#side h2{{font-size:14px;margin:0 0 8px}} #side li{{font-size:12px;line-height:1.9;list-style:none}}
.legend{{font-size:12px;color:#6b7280;margin-top:8px}}
</style></head><body>
<header><h1>新闻事件知识图谱</h1>
<p class="sub">节点大小 = 关联度（相关节点 + 分支数）· 颜色深浅 = 重复次数 × 时间近度（越深越热/越近）· 实线箭头=演进 · 虚线=相关</p></header>
<div class="bar">
  <span>显示</span>
  <button id="b-all" class="on" onclick="setMode('all')">全部关系</button>
  <button id="b-chain" onclick="setMode('chain')">仅演进链</button>
  <span style="margin-left:10px">规模</span>
  <button onclick="setN(120)">120</button>
  <button class="on" onclick="setN(250)">250</button>
  <button onclick="setN(400)">400</button>
  <span style="margin-left:10px">类别</span>
  <select id="cat" onchange="setCat(this.value)"><option value="">全部</option></select>
</div>
<main>
  <div id="chart"></div>
  <div id="side"><h2>演进故事链（Top）</h2><ul id="chains">{chains_html or '<li>（当前范围内无完整故事链）</li>'}</ul>
  <div class="legend" id="stat"></div></div>
</main>
<script>
var DATA = {data_json};
var CATS = {cats_json};
var MODE = 'all', NCAP = 250, CAT = '';
var chart = echarts.init(document.getElementById('chart'));
CATS.forEach(function(c){{var o=document.createElement('option');o.value=c;o.text=c;document.getElementById('cat').add(o);}});
function colorOf(c){{
  var map={{"时政":"#185fa5","财经":"#854f0b","科技":"#534ab7","体育":"#0f6e56","娱乐":"#993556",
          "国际":"#a32d2d","社会民生":"#27500a","健康科普":"#1d9e75","其他":"#888780"}};
  return map[c]||"#888780";
}}
function render(){{
  var chainIds = {{}};
  DATA.chains.forEach(function(ch){{ch.forEach(function(i){{chainIds[i]=1;}});}});
  var nodes = DATA.nodes.filter(function(n){{
    if (CAT && n.category !== CAT) return false;
    if (MODE==='chain' && !chainIds[n.id]) return false;
    return true;
  }}).slice(0, NCAP);
  var ids = {{}}; nodes.forEach(function(n){{ids[n.id]=1;}});
  var edges = DATA.edges.filter(function(e){{
    if (!ids[e.source] || !ids[e.target]) return false;
    if (MODE==='chain' && e.type!=='follows') return false;
    return true;
  }});
  var opt = {{
    tooltip: {{formatter:function(p){{
      if(p.dataType==='node'){{var d=p.data;return '<b>'+d.name+'</b><br>'+d.category+' · '+d.phase+
        '<br>累计 '+d.value+' 次 · '+d.source_count+' 源 · 关联边 '+d.degree+
        '<br>'+d.first_seen+' ~ '+d.last_seen+'（热度强度 '+d.intensity+'）'+
        '<br>'+(d.summary||'');}}
      return p.data.label+' ('+p.data.weight+')';
    }}}},
    legend: [{{data: CATS}}],
    series: [{{type:'graph', layout:'force', roam:true, draggable:true,
      force:{{repulsion:120, edgeLength:[60,160], gravity:0.08}},
      categories: CATS.map(function(c){{return {{name:c, itemStyle:{{color:colorOf(c)}}}};}}),
      label:{{show:true, position:'right', fontSize:10, color:'#444441',
             formatter:function(p){{return p.data.name.slice(0,14);}}}},
      edgeLabel:{{show:false}},
      data: nodes.map(function(n){{
        return {{id:n.id, name:n.name, value:n.count, category:CATS.indexOf(n.category),
                symbolSize: Math.max(12, Math.min(60, 12 + Math.log2(1 + n.degree) * 9)),
                itemStyle: {{color: n.color, borderColor:'#fff', borderWidth:0.5}},
                summary:n.summary, first_seen:n.first_seen, last_seen:n.last_seen,
                source_count:n.source_count, phase:n.phase,
                degree:n.degree, intensity:n.intensity}};
      }}),
      links: edges.map(function(e){{
        return {{source:e.source, target:e.target, value:e.weight,
          label:{{show:false}},
          lineStyle:{{width:Math.max(1, e.weight*3),
            type: e.type==='follows'?'solid':'dashed',
            color: e.type==='follows'?'#185fa5':'#b4b2a9',
            curveness: e.type==='follows'?0.12:0.08,
            opacity: e.type==='follows'?0.9:0.45}},
          symbol: e.type==='follows'?[null,'arrow']:[null,null],
          symbolSize: e.type==='follows'?7:0}};
      }})
    }}]
  }};
  chart.setOption(opt, true);
  document.getElementById('stat').textContent =
    '节点 '+nodes.length+' · 演进边 '+edges.filter(function(e){{return e.type==='follows';}}).length+
    ' · 相关边 '+edges.filter(function(e){{return e.type==='related';}}).length+
    ' · 故事链 '+DATA.chains.length+' 条';
}}
function setMode(m){{MODE=m;
  document.getElementById('b-all').className = m==='all'?'on':'';
  document.getElementById('b-chain').className = m==='chain'?'on':'';
  render();}}
function setN(n){{NCAP=n; render();}}
function setCat(c){{CAT=c; render();}}
render();
window.addEventListener('resize', function(){{chart.resize();}});
</script></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def build_and_save(events, max_nodes=250):
    g = build_graph(events)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "knowledge_graph.json"), "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=1)
    save_graphml(g, os.path.join(DATA_DIR, "knowledge_graph.graphml"))
    save_cypher(g, os.path.join(DATA_DIR, "knowledge_graph.cypher"))
    save_html(g, os.path.join(REPORT_DIR, "knowledge_graph.html"), max_nodes=max_nodes)
    return g
