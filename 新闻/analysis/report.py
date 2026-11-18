# -*- coding: utf-8 -*-
"""
M6 · 脉络报告生成（构建文档 §9/§12）
Markdown + HTML 双格式，落盘 reports/。
"""
import os
import html as _html
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(BASE_DIR, "reports")


def _event_block(ev, bursts):
    days = ev["days"]
    span = f"{days[0][5:]} → {days[-1][5:]}" if len(days) > 1 else days[0][5:]
    head = (f"【事件】{ev['name']}　[{ev['category']}]　"
            f"（累计 {ev['count']} 次 · {span} · 跨 {len(days)} 个观测日 · "
            f"阶段：{ev['phase']} · {ev['source_count']} 个来源）")
    lines = [head]
    for it in ev.get("timeline", []):
        lines.append(f"  · 第{it['seq']}次 {it['date'][5:]} {it['source']}  「{it['title']}」")
    for b in bursts:
        lines.append(f"  ⚡ 突发：{b['date'][5:]} 当日报道由 {b['daily_before']} 条升至 {b['daily_count']} 条")
    lines.append(f"  脉络摘要：{ev['summary']}")
    if ev.get("related"):
        lines.append("  相关事件：")
        for i, r in enumerate(ev["related"]):
            branch = "└─" if i == len(ev["related"]) - 1 else "├─"
            lines.append(f"  {branch} 「{r['name'][:24]}」 出现 {r['count']} 次（sim={r['similarity']}）")
    return "\n".join(lines)


def render_markdown(events, cal, stats):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    obs = cal.get("observed", [])
    lines = [
        "# 新闻事件脉络报告",
        f"",
        f"> 生成于 {now}　观测期 {obs[0] if obs else '?'} ~ {obs[-1] if obs else '?'}",
        f"> 观测日 {stats.get('days', len(obs))} · 标题记录 {stats.get('records', 0)} · "
        f"事件 {len(events)} · 缺日 {len(cal.get('missing', []))} 天",
        "",
        "## 事件脉络（按 多源佐证 × 出现次数 排序）",
        "",
    ]
    for ev in events:
        lines.append(_event_block(ev, ev.get("bursts", [])))
        lines.append("")
    return "\n".join(lines)


def render_html(md_events, cal, stats, events):
    esc = _html.escape
    cards = []
    for ev in events:
        rel = "".join(
            f"<li>「{esc(r['name'][:24])}」 出现 {r['count']} 次（sim={r['similarity']}）</li>"
            for r in ev.get("related", []))
        burst = "".join(
            f"<div class='burst'>⚡ 突发：{b['date'][5:]} 当日报道 {b['daily_before']} → {b['daily_count']} 条</div>"
            for b in ev.get("bursts", []))
        items = "".join(
            f"<li><span class='d'>{it['date'][5:]}</span> {esc(it['source'])}　{esc(it['title'])}</li>"
            for it in ev.get("timeline", []))
        cards.append(f"""
<div class="ev">
  <h3>{esc(ev['name'])} <span class="tag">{esc(ev['category'])}</span>
      <span class="tag phase">{esc(ev['phase'])}</span></h3>
  <div class="meta">累计 {ev['count']} 次 · 跨 {len(ev['days'])} 个观测日 · {ev['source_count']} 个来源 · {ev['event_id']}</div>
  <ul>{items}</ul>
  {burst}
  <div class="sum">{esc(ev.get('summary', ''))}</div>
  {f'<div class="rel"><b>相关事件</b><ul>{rel}</ul></div>' if rel else ''}
</div>""")
    obs = cal.get("observed", [])
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>新闻事件脉络报告</title>
<style>
body{{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#f6f7f9;margin:0;padding:24px;color:#1f2937}}
h1{{font-size:22px}} .stats{{color:#6b7280;margin-bottom:18px}}
.ev{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;margin:14px 0}}
.ev h3{{margin:0 0 6px;font-size:16px}}
.tag{{display:inline-block;background:#e6f1fb;color:#185fa5;border-radius:6px;padding:1px 8px;font-size:12px;margin-left:6px;vertical-align:middle}}
.tag.phase{{background:#faeeda;color:#854f0b}}
.meta{{color:#6b7280;font-size:12px;margin-bottom:8px}}
.ev ul{{margin:6px 0;padding-left:20px}} .ev li{{font-size:13px;line-height:1.8}}
.d{{color:#9ca3af;font-family:monospace}} .burst{{color:#a32d2d;font-size:13px;margin:4px 0}}
.sum{{background:#f1efe8;border-radius:8px;padding:8px 12px;font-size:13px;margin:8px 0}}
.rel{{border-top:1px dashed #e5e7eb;padding-top:8px;font-size:13px}}
</style></head><body>
<h1>新闻事件脉络报告</h1>
<div class="stats">观测期 {obs[0] if obs else '?'} ~ {obs[-1] if obs else '?'} · 观测日 {len(obs)} ·
记录 {stats.get('records', 0)} · 事件 {len(events)} · 缺日 {len(cal.get('missing', []))} 天</div>
{''.join(cards)}
</body></html>"""


def write_reports(events, cal, stats):
    """落盘 reports/report_YYYYMMDD.{md,html}，返回 (md_path, html_path)。"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    day = datetime.datetime.now().strftime("%Y%m%d")
    md = render_markdown(events, cal, stats)
    htm = render_html(md, cal, stats, events)
    md_path = os.path.join(REPORT_DIR, f"report_{day}.md")
    html_path = os.path.join(REPORT_DIR, f"report_{day}.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(htm)
    return md_path, html_path
