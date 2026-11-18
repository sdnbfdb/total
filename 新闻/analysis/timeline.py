# -*- coding: utf-8 -*-
"""
M6 · 时间线构建（构建文档 §5.1）
把事件记录按观测日展开成时间线条目。
"""


def build_timeline(event):
    """→ [{seq, date, source, title, occurrences}]"""
    items = []
    seq = 0
    for rec in sorted(event.get("records", []), key=lambda r: (r["date"], r["source"] or "")):
        seq += 1
        items.append({
            "seq": seq,
            "date": rec["date"],
            "source": rec.get("source", ""),
            "title": rec.get("title", ""),
            "occurrences": rec.get("occurrences", 1),
        })
    return items
