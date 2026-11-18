# -*- coding: utf-8 -*-
"""
M2b · 正文获取与利用（构建文档 §7.8）
只回抓文章页 URL；缓存抓一次用终身；缺失优雅降级 title-only。
"""
import os
import re
import json
import time
import hashlib
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART_DIR = os.path.join(BASE_DIR, "data", "articles")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MIN_INTERVAL = 1.0        # 全局限速 ≤1 请求/秒（§7.8）
TIMEOUT = 15
MAX_RETRY = 2
BODY_MAX = 2000

_last_fetch = 0.0

# 搜索/话题页：没有可抽取正文，标 search_url 跳过（§7.8）
SEARCH_URL_RES = [
    re.compile(r"m\.baidu\.com/s\?"),
    re.compile(r"www\.baidu\.com/s\?"),
    re.compile(r"s\.weibo\.com/"),
    re.compile(r"weibo\.com/search"),
    re.compile(r"toutiao\.com/trending/"),
    re.compile(r"tieba\.baidu\.com/hottopic/browse"),
    re.compile(r"zhihu\.com/search"),
]

_TAG_RE = re.compile(r"<(script|style)[\s\S]*?</\1>", re.I)
_ANY_TAG_RE = re.compile(r"<[^>]+>")

# 反爬/验证页特征：抽取结果命中则按 empty 降级（§13）
JUNK_MARKERS = ["安全检测", "正在检测当前网络环境", "访问验证", "人机验证",
                "captcha", "请开启 JavaScript", "请启用 JavaScript", "验证您是人类"]


def is_search_url(url):
    return any(r.search(url or "") for r in SEARCH_URL_RES)


def _cache_path(url):
    h = hashlib.md5((url or "").encode("utf-8")).hexdigest()
    return os.path.join(ART_DIR, h + ".json")


def load_cached(url):
    p = _cache_path(url)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _save(url, payload):
    os.makedirs(ART_DIR, exist_ok=True)
    with open(_cache_path(url), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _extract_text(html):
    """trafilatura 优先，失败回退正则去标签（§7.8）。"""
    try:
        import trafilatura
        t = trafilatura.extract(html, include_comments=False, include_tables=False)
        if t and len(t.strip()) >= 50:
            return t.strip()[:BODY_MAX]
    except Exception:
        pass
    t = _TAG_RE.sub(" ", html)
    t = _ANY_TAG_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:BODY_MAX] if len(t) >= 50 else ""


def fetch_article(url):
    """回抓单篇 → {url, status, text, fetched_at}。status: ok/empty/dead/search_url。"""
    global _last_fetch
    if not url:
        return {"url": url, "status": "empty", "text": ""}
    cached = load_cached(url)
    if cached:
        return cached
    if is_search_url(url):
        payload = {"url": url, "status": "search_url", "text": "", "fetched_at": time.time()}
        _save(url, payload)
        return payload

    wait = MIN_INTERVAL - (time.time() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.time()

    status, text = "dead", ""
    for _ in range(MAX_RETRY + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
            for enc in ("utf-8", "gb18030", "gbk"):
                try:
                    html = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                html = raw.decode("utf-8", errors="ignore")
            text = _extract_text(html)
            if any(jm in text[:300] for jm in JUNK_MARKERS):
                text = ""
            status = "ok" if text else "empty"
            break
        except Exception:
            time.sleep(1.5)
    payload = {"url": url, "status": status, "text": text, "fetched_at": time.time()}
    _save(url, payload)
    return payload


def backfill(records, limit=None, verbose=False):
    """按需批量回抓（历史回填/增量），跳过已缓存与搜索页。返回统计。"""
    done = {"ok": 0, "empty": 0, "dead": 0, "search_url": 0, "skipped": 0}
    n = 0
    for rec in records:
        if limit is not None and n >= limit:
            break
        url = rec.get("url") or ""
        if not url:
            continue
        if load_cached(url):
            done["skipped"] += 1
            continue
        r = fetch_article(url)
        done[r["status"]] = done.get(r["status"], 0) + 1
        n += 1
        if verbose and n % 20 == 0:
            print(f"  [content] 已回抓 {n} 篇 …")
    return done


def body_pool(event):
    """事件级正文池（§7.8 第 2 层）：成员记录的正文 + snippet，全事件共享。"""
    pool = []
    for rec in event.get("records", []):
        sn = (rec.get("snippet") or "").strip()
        if sn and len(sn) >= 20:
            pool.append(sn)
        c = load_cached(rec.get("url") or "")
        if c and c.get("status") == "ok" and c.get("text"):
            pool.append(c["text"][:300])
        if len(pool) >= 8:
            break
    return pool
