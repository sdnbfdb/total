# -*- coding: utf-8 -*-
"""
M1 · 快照解析层（构建文档 §7.1）
解析 news_YYYYMMDD_HHMMSS.txt → 标题记录（含 snippet）+ 观测日历。
只认行首的【源名】为数据源块边界——meta 摘要里出现的【】不会误切（§13 解析陷阱）。
"""
import os
import re
import glob
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SNAPSHOT_RE = re.compile(r"^news_(\d{8})_(\d{6})\.txt$")
BLOCK_RE = re.compile(r"^【(.+?)】\s*$")
COUNT_RE = re.compile(r"^（共\s*(\d+)\s*条）")
ITEM_RE = re.compile(r"^(\d{1,3})\.\s+(.+)$")
URL_RE = re.compile(r"^\s+(https?://\S+?)\s*$")
HOT_RE = re.compile(r"(?:热度|讨论|阅读)[:：]\s*([\w.]+)")
STRIP_PREFIX_RE = re.compile(r"^(?:热度|讨论|阅读|时间|来源)[:：]\s*\S+\s*")

MIN_VALID_ITEMS = 100   # 观测日有效条数下限（§7.1 空快照判定）
SNIPPET_MAX = 200       # snippet 截断长度

# 过期存档过滤：人民网旧 RSS（自 2025-06-05 停更）曾每天注入 100 条一年前的旧闻，
# 而记录日期取自快照文件名，这些旧闻会被误当成当日新报道参与计数/突发/阶段判定。
STALE_LINK_DATE_RE = re.compile(r"/n1/(\d{4})/(\d{2})(\d{2})/")
STALE_META_DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
MAX_ARTICLE_AGE_DAYS = 3    # 文章日期早于快照日期超过 3 天 → 判为过期存档
_stale_dropped = 0          # 本次 parse_all 丢弃条数（写入 stats）


def _article_date(url, meta_lines, source):
    """从链接或 meta 的 pubDate 还原文章真实发布日期；取不到返回 None。"""
    m = STALE_LINK_DATE_RE.search(url or "")
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # meta 里的 YYYY-MM-DD 只对官媒 RSS 源启用，避免误伤滚动新闻里的正常日期字段
    if source and source.startswith("人民日报"):
        for ln in meta_lines:
            mm = STALE_META_DATE_RE.search(ln)
            if mm:
                try:
                    return datetime.date(int(mm.group(1)), int(mm.group(2)), int(mm.group(3)))
                except ValueError:
                    pass
    return None


def _parse_meta(meta_lines):
    """meta 行 → (hot, snippet)。"""
    hot = ""
    rest = []
    for ln in meta_lines:
        if not hot:
            m = HOT_RE.search(ln)
            if m:
                hot = m.group(1)
        s = STRIP_PREFIX_RE.sub("", ln.strip()).strip()
        if s and len(s) >= 4:
            rest.append(s)
    return hot, " ".join(rest)[:SNIPPET_MAX]


def parse_file(path):
    """解析单个快照，返回记录列表（dict）。"""
    m = SNAPSHOT_RE.match(os.path.basename(path))
    if not m:
        return []
    d = m.group(1)
    date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    snap_date = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    with open(path, encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()

    records = []
    source = None
    failed = False
    cur = None          # 当前条目 {"title","url","meta_lines"}
    meta_buf = []

    def flush():
        global _stale_dropped
        nonlocal cur, meta_buf
        if cur and not failed and cur["title"]:
            title = cur["title"].strip()
            # 过滤栏目页/聚合简报标题（每天重复的源页面名，会形成假巨型簇）
            agg_markers = ("新闻:快讯", "新闻简报", "每日热点", "_网易订阅",
                           "新闻早知道", "热点不容错过", "全球热点 - 知乎")
            is_agg = (any(m in title for m in agg_markers)
                      or (len(title) >= 45 and sum(title.count(c) for c in ",，|、") >= 2))
            art_date = _article_date(cur.get("url", ""), meta_buf, source)
            is_stale = art_date is not None and (snap_date - art_date).days > MAX_ARTICLE_AGE_DAYS
            if is_stale:
                _stale_dropped += 1
            elif not is_agg:
                hot, snippet = _parse_meta(meta_buf)
                records.append({
                    "date": date,
                    "source": source,
                    "title": title,
                    "url": cur.get("url", ""),
                    "hot": hot,
                    "snippet": snippet,
                    "file": os.path.basename(path),
                })
        cur, meta_buf = None, []

    def is_block_header(i):
        """行首【…】只有后跟『（共 N 条）』/条目/失败标记才是数据源块头（防幻影源）。"""
        bm = BLOCK_RE.match(lines[i])
        if not bm:
            return None
        for j in range(i + 1, min(i + 3, len(lines))):
            nxt = lines[j].strip()
            if not nxt:
                continue
            return bm.group(1).strip() if (
                COUNT_RE.match(nxt) or ITEM_RE.match(nxt) or nxt.startswith("[请求失败]")
            ) else None
        return None

    for idx, line in enumerate(lines):
        name = is_block_header(idx)
        if name is not None and not line.startswith((" ", "\t")):
            flush()
            source = name
            failed = False
            continue
        if source is None:
            continue
        if line.strip().startswith("[请求失败]"):
            flush()
            failed = True
            continue
        if COUNT_RE.match(line.strip()):
            continue
        im = ITEM_RE.match(line)
        if im:
            flush()
            cur = {"title": im.group(2), "url": ""}
            continue
        um = URL_RE.match(line)
        if um and cur is not None:
            cur["url"] = um.group(1)
            continue
        if line.startswith((" ", "\t")) and cur is not None:
            meta_buf.append(line)
            continue
    flush()
    return records


def build_calendar(records, file_days):
    """
    观测日历：观测日 = 有效条数 ≥ MIN_VALID_ITEMS 的日期；
    缺日 = 首末观测日之间没有快照的日期；无效 = 有快照但条数过少。
    """
    by_day = {}
    for r in records:
        by_day[r["date"]] = by_day.get(r["date"], 0) + 1
    observed = sorted(d for d, n in by_day.items() if n >= MIN_VALID_ITEMS)
    invalid = sorted(set(file_days) - set(observed))
    missing = []
    if observed:
        cur = datetime.date.fromisoformat(observed[0])
        end = datetime.date.fromisoformat(observed[-1])
        have = set(observed)
        while cur <= end:
            if cur.isoformat() not in have:
                missing.append(cur.isoformat())
            cur += datetime.timedelta(days=1)
    return {
        "observed": observed,
        "invalid": invalid,
        "missing": missing,
        "per_day_counts": {d: n for d, n in sorted(by_day.items())},
    }


def parse_all(base_dir=None):
    """解析全部快照 → (records, calendar, stats)。"""
    global _stale_dropped
    _stale_dropped = 0
    base_dir = base_dir or BASE_DIR
    paths = sorted(glob.glob(os.path.join(base_dir, "news_*.txt")))
    paths = [p for p in paths if SNAPSHOT_RE.match(os.path.basename(p))]
    records, file_days = [], []
    for p in paths:
        rs = parse_file(p)
        if rs:
            file_days.append(rs[0]["date"])
            records.extend(rs)
    records.sort(key=lambda r: (r["date"], r["source"] or "", r["title"]))
    calendar = build_calendar(records, file_days)
    stats = {
        "files": len(paths),
        "records": len(records),
        "days": len(calendar["observed"]),
        "sources": sorted({r["source"] for r in records if r["source"]}),
        "stale_dropped": _stale_dropped,
    }
    return records, calendar, stats
