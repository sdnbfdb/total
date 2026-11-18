# -*- coding: utf-8 -*-
"""
M3 · TDT：突发检测 + 时间线摘要（构建文档 §7.4）
条数口径；缺日不参与环比、不重置计数（观测日历语义）。
"""


def daily_counts(event):
    """事件逐「观测日」条数序列（只返回有报道的日期）。"""
    cnt = {}
    for rec in event.get("records", []):
        cnt[rec["date"]] = cnt.get(rec["date"], 0) + rec.get("occurrences", 1)
    return dict(sorted(cnt.items()))


def detect_bursts(event, observed_days):
    """
    突发拐点：当日条数 ≥ 2 且 ≥ 此前观测日均值×3（且环比上升）。
    返回 [{date, count_before(累计), count_after(累计), daily_before, daily_count}]。
    """
    cnt = daily_counts(event)
    bursts = []
    cum = 0
    prev_daily = None
    hist = []  # 此前观测日的条数（缺日记 0 不进入：只用有记录的观测日）
    for d in observed_days:
        c = cnt.get(d, 0)
        if c == 0:
            continue  # 缺日/无报道观测日：跳过，不重置
        mean_prev = (sum(hist) / len(hist)) if hist else 0.0
        if hist and c >= 2 and c > (prev_daily or 0) and c >= max(2.0, 3 * mean_prev):
            bursts.append({
                "date": d,
                "count_before": cum,
                "count_after": cum + c,
                "daily_before": prev_daily or 0,
                "daily_count": c,
            })
        cum += c
        hist.append(c)
        prev_daily = c
    return bursts


def timeline_summary(event, bursts):
    """规则模板脉络摘要（M7 可换 LLM）。"""
    name = event["name"][:18]
    n = event["count"]
    days = event["days"]
    k = event["source_count"]
    parts = [f"「{name}」自 {days[0][5:]} 首现"]
    if bursts:
        b = bursts[0]
        parts.append(f"{b['date'][5:]} 报道量骤增（{b['daily_before']}→{b['daily_count']} 条/日）")
    if len(days) > 1:
        parts.append(f"至 {days[-1][5:]} 累计 {n} 次、跨 {len(days)} 个观测日、{k} 个来源")
    else:
        parts.append(f"当日累计 {n} 次、{k} 个来源")
    return "，".join(parts) + "。"
