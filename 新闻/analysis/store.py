# -*- coding: utf-8 -*-
"""事件库持久化（构建文档 §6.4）：data/*.json。"""
import os
import json
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def _path(name):
    return os.path.join(DATA_DIR, name)


def _dump(path, obj):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def save_events(events, meta=None):
    payload = {
        "meta": meta or {},
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "events": events,
    }
    _dump(_path("events.json"), payload)


def load_events():
    p = _path("events.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_calendar(cal):
    _dump(_path("calendar.json"), cal)


def load_calendar():
    p = _path("calendar.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_eval_pairs(pairs):
    _dump(_path("eval_pairs.json"), pairs)


def load_eval_pairs():
    p = _path("eval_pairs.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)
