# -*- coding: utf-8 -*-
"""
M4 · Story-identity：阶段追踪 + 多源佐证（构建文档 §7.5）
全部按观测日计；缺日不计入「连续 N 天无新增」。
"""

QUIET_N = 3  # 平息判定：连续 N 个观测日无新增


def judge_phase(event, observed_days, bursts):
    """
    酝酿 / 爆发 / 发酵 / 缓慢发酵 / 平息。
    event 需含 count, days, last_seen；bursts 为 tdt.detect_bursts 输出。
    """
    count = event["count"]
    days = set(event["days"])
    daily = {}
    for rec in event.get("records", []):
        daily[rec["date"]] = daily.get(rec["date"], 0) + rec.get("occurrences", 1)
    max_daily = max(daily.values()) if daily else 0

    # 平息：最近一次出现距最后观测日超过 QUIET_N 个观测日
    if observed_days:
        idx = {d: i for i, d in enumerate(observed_days)}
        last_i = idx.get(event["last_seen"])
        end_i = len(observed_days) - 1
        if last_i is not None and end_i - last_i >= QUIET_N:
            return "平息"

    if bursts:
        # 爆发：拐点就在最近一个报道日；否则已进入发酵
        if bursts[-1]["date"] == event["last_seen"]:
            return "爆发"
        return "发酵"

    if count <= 2 and max_daily <= 1:
        return "酝酿"
    if count >= 3 and len(days) >= 3:
        return "缓慢发酵"
    return "发酵"
