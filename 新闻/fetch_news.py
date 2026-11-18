# -*- coding: utf-8 -*-
"""
新闻抓取脚本：请求所有可用接口，提取实际新闻，保存为带时间戳的 txt。
密钥从 .env 读取。
"""
import os
import re
import sys
import json
import time
import datetime
import socket
import urllib.request
import urllib.parse
import urllib.error
import smtplib
import ssl
import html
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
ZHIHU_QUERY = "热点新闻"


def load_env(path=None):
    if path is None:
        path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# Windows 控制台默认 GBK 无法输出部分 Unicode（如 ▶），强制使用 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

load_env()
JUHE_NEWS_API_KEY = os.getenv("JUHE_NEWS_API_KEY", "")
ZHIHU_ACCESS_SECRET = os.getenv("ZHIHU_ACCESS_SECRET", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
USE_PROXY = os.getenv("USE_PROXY", "0") == "1"
PROXY_HOST = os.getenv("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "1080"))
SMTP_HOST = os.getenv("MAIL_SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("MAIL_SMTP_PORT", "465"))
MAIL_FROM = os.getenv("MAIL_FROM", "")
MAIL_AUTH_CODE = os.getenv("MAIL_AUTH_CODE", "")
MAIL_TO = os.getenv("MAIL_TO", "")


# 迷雾通 SOCKS5 代理（仅对标记 proxy=True 的国外源启用；用 PySocks 临时接管 socket）
_socks = None
if USE_PROXY:
    try:
        import socks as _socks
    except ImportError:
        _socks = None

_orig_socket = socket.socket


def _urlopen(req, timeout, use_proxy):
    if use_proxy and _socks is not None:
        _socks.set_default_proxy(_socks.SOCKS5, PROXY_HOST, PROXY_PORT)
        socket.socket = _socks.socksocket
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        finally:
            socket.socket = _orig_socket
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_json(url, headers=None, timeout=20, use_proxy=False):
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with _urlopen(req, timeout, use_proxy) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_text(url, headers=None, timeout=20, use_proxy=False):
    """抓取文本（RSS/HTML），按常见编码依次尝试解码。"""
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with _urlopen(req, timeout, use_proxy) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


LUOYING_INTERVAL = 60
_luoying_last_time = 0.0


def fetch_source(src):
    """抓取单个数据源，对 luoying 做限流等待与 429 重试。"""
    global _luoying_last_time
    headers = src.get("headers")
    if headers and "X-Request-Timestamp" in headers:
        headers["X-Request-Timestamp"] = str(int(time.time()))
    rate_limit = src.get("rate_limit")
    if rate_limit:
        wait = LUOYING_INTERVAL - (time.time() - _luoying_last_time)
        if wait > 0:
            time.sleep(wait)
    kind = src.get("kind", "json")
    use_proxy = bool(src.get("proxy"))
    try:
        if kind == "json":
            return fetch_json(src["url"], headers, use_proxy=use_proxy)
        return fetch_text(src["url"], headers, use_proxy=use_proxy)
    except urllib.error.HTTPError as e:
        if rate_limit and e.code == 429:
            time.sleep(LUOYING_INTERVAL)
            if kind == "json":
                return fetch_json(src["url"], headers, use_proxy=use_proxy)
            return fetch_text(src["url"], headers, use_proxy=use_proxy)
        raise
    finally:
        if rate_limit:
            _luoying_last_time = time.time()


def cut(text, n):
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


# ---------- 各接口解析 ----------

def parse_baidu_top(data):
    items, seen = [], set()

    def walk(node):
        if isinstance(node, dict):
            word = node.get("word")
            if isinstance(word, str) and word.strip() and word not in seen:
                seen.add(word)
                hot = node.get("hotTag") or ""
                items.append({"title": word, "url": node.get("url", ""),
                              "meta": f"热度:{hot}" if hot else ""})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data.get("data", {}))
    return items[:50]


def parse_toutiao(data):
    items = []
    for it in data.get("data", [])[:50]:
        hot = it.get("HotValue") or ""
        items.append({"title": it.get("Title", ""), "url": it.get("Url", ""),
                      "meta": f"热度:{hot}" if hot else ""})
    return items


def parse_tieba(data):
    items = []
    tl = data.get("data", {}).get("bang_topic", {}).get("topic_list", [])
    for it in tl[:50]:
        disc = it.get("discuss_num") or ""
        abstract = cut(it.get("abstract"), 80)
        meta = f"讨论:{disc}" if disc else ""
        if abstract:
            meta = (meta + "  " + abstract) if meta else abstract
        items.append({"title": it.get("topic_name", ""),
                      "url": it.get("topic_url", ""), "meta": meta})
    return items


def parse_sina(data):
    items = []
    for it in data.get("result", {}).get("data", [])[:50]:
        ctime = it.get("ctime") or ""
        timestamp = ""
        if isinstance(ctime, (int, float)) and ctime:
            timestamp = datetime.datetime.fromtimestamp(int(ctime)).strftime("%m-%d %H:%M")
        items.append({"title": it.get("title", ""), "url": it.get("url", ""),
                      "meta": f"时间:{timestamp}" if timestamp else ""})
    return items


def parse_ithome_news(data):
    items = []
    for it in data.get("newslist", [])[:50]:
        url = it.get("url", "")
        if url.startswith("/"):
            url = "https://www.ithome.com" + url
        post = (it.get("postdate") or "")[:16].replace("T", " ")
        desc = cut(it.get("description"), 100)
        meta = post
        if desc:
            meta = (meta + "  " + desc) if meta else desc
        items.append({"title": it.get("title", ""), "url": url, "meta": meta})
    return items


def parse_36kr(data):
    items = []
    for it in data.get("data", [])[:50]:
        tm = it.get("templateMaterial", {})
        item_id = it.get("itemId", "")
        author = tm.get("authorName") or ""
        read = tm.get("statRead") or ""
        meta = f"作者:{author}" if author else ""
        if read:
            meta = (meta + f"  阅读:{read}") if meta else f"阅读:{read}"
        url = f"https://36kr.com/p/{item_id}" if item_id else ""
        items.append({"title": tm.get("widgetTitle", ""), "url": url, "meta": meta})
    return items


def parse_xcvts_ithome(data):
    items = []
    for it in data.get("data", [])[:50]:
        cat = it.get("category") or ""
        t = it.get("time") or ""
        meta = cat
        if t:
            meta = (meta + "  " + t) if meta else t
        items.append({"title": it.get("title", ""), "url": it.get("link", ""), "meta": meta})
    return items


def parse_eastmoney(data):
    items = []
    for it in data.get("data", [])[:50]:
        t = it.get("time") or ""
        content = cut(it.get("content"), 100)
        meta = f"时间:{t}" if t else ""
        if content:
            meta = (meta + "  " + content) if meta else content
        items.append({"title": it.get("title", ""), "url": it.get("url", ""), "meta": meta})
    return items


def parse_luoying(data):
    items = []
    for it in data.get("data", {}).get("list", [])[:50]:
        heat = it.get("heat") or it.get("hot") or ""
        items.append({"title": it.get("title", ""), "url": it.get("url", ""),
                      "meta": f"热度:{heat}" if heat else ""})
    return items


def parse_juhe(data):
    items = []
    for it in data.get("result", {}).get("data", [])[:50]:
        cat = it.get("category") or ""
        author = it.get("author_name") or ""
        date = it.get("date") or ""
        meta = cat
        if author:
            meta = (meta + "  " + author) if meta else author
        if date:
            meta = (meta + "  " + date) if meta else date
        items.append({"title": it.get("title", ""), "url": it.get("url", ""), "meta": meta})
    return items


def parse_zhihu(data):
    items = []
    for it in data.get("Data", {}).get("Items", [])[:20]:
        items.append({"title": it.get("Title", ""), "url": it.get("Url", ""),
                      "meta": cut(it.get("ContentText"), 120)})
    return items


# ---------- 权威官媒/通讯社解析（人民日报 / 新华社 / 新闻联播 / 路透社 / 美联社） ----------

def parse_people_rss(text):
    """解析人民网官方 RSS（人民日报），返回标题/链接/日期/来源。"""
    items = []
    root = ET.fromstring(text)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        author = (item.findtext("author") or "").strip()
        if not title:
            continue
        meta = f"来源:{author}" if author else ""
        if pub:
            meta = (meta + "  " + pub) if meta else pub
        items.append({"title": title, "url": link, "meta": meta})
    return items[:50]


# 人民网频道页链接形如 /n1/2026/1115/c1002-40834108.html，日期可直接从 URL 读出
PEOPLE_LINK_RE = re.compile(
    r"""<a\b[^>]*?href=['"]([^'"]*?/n1/(\d{4})/(\d{2})(\d{2})/[^'"]+?\.html)['"][^>]*>(.*?)</a>""",
    re.I | re.S)


def parse_people_html(text):
    """解析人民网频道页（HTML），只保留 URL 标注为当日/近日的文章。

    人民网旧 RSS（politics.xml / world.xml）自 2025-06-05 起停止更新，是固定
    100 条的静态存档，每天抓到的都是同一批旧闻；改抓频道页并按 URL 日期过滤，
    当日条目不足时才回退到近 PEOPLE_FRESH_DAYS 天，避免旧闻污染事件库。
    """
    today = datetime.date.today()
    cand, seen = [], set()
    for url, y, mo, dd, inner in PEOPLE_LINK_RE.findall(text):
        try:
            pub = datetime.date(int(y), int(mo), int(dd))
        except ValueError:
            continue
        age = (today - pub).days
        if age < 0 or age > PEOPLE_FRESH_DAYS:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", inner))
        title = " ".join(title.replace("\xa0", " ").split())
        if len(title) < 4:
            continue
        if url.startswith("//"):
            url = "http:" + url
        elif url.startswith("/"):
            url = "http://www.people.com.cn" + url
        if url in seen:
            continue
        seen.add(url)
        cand.append({"title": title, "url": url, "meta": f"时间:{pub.isoformat()}"})
    today_items = [it for it in cand if it["meta"].endswith(today.isoformat())]
    chosen = today_items if len(today_items) >= 5 else cand
    return chosen[:50]


def _extract_links(text, url_re):
    """按正则从 HTML 提取去重后的标题+链接。"""
    items, seen = [], set()
    for m in url_re.finditer(text):
        url = m.group(1).strip()
        title = re.sub(r"<[^>]+>", "", m.group(2) or "").strip()
        title = title.replace("\xa0", " ").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "url": url, "meta": ""})
    return items[:50]


def parse_xinhua_html(text):
    """解析新华网页面标题列表（新华社），兼容单/双引号链接。"""
    url_re = re.compile(r"""href=['"](https?://(?:www\.)?news\.cn/[^'"]+/c\.html)['"][^>]*>([^<]{4,})<""")
    return _extract_links(text, url_re)


def parse_cctv_xwlb(text):
    """解析央视网《新闻联播》栏目页，提取当天条目标题与链接。"""
    url_re = re.compile(r'href="(https://tv\.cctv\.com/\d{4}/\d{2}/\d{2}/VIDE[^"]+\.shtml)"[^>]*title="([^"]+)"')
    return _extract_links(text, url_re)


def parse_newsapi(data):
    """解析 NewsAPI.org /v2/everything 返回（路透社/美联社）。"""
    items = []
    for a in data.get("articles", [])[:50]:
        src_name = (a.get("source") or {}).get("name", "")
        t = (a.get("publishedAt") or "")[:10]
        meta = f"来源:{src_name}" if src_name else ""
        if t:
            meta = (meta + "  " + t) if meta else t
        items.append({"title": a.get("title", ""), "url": a.get("url", ""), "meta": meta})
    return items


zhihu_url = "https://developer.zhihu.com/api/v1/content/global_search?" + urllib.parse.urlencode(
    {"Query": ZHIHU_QUERY, "Count": 10}
)

SOURCES = [
    {"name": "百度热搜", "url": "https://top.baidu.com/api/board?platform=wise&tab=realtime", "parse": parse_baidu_top},
    {"name": "今日头条热榜", "url": "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", "parse": parse_toutiao},
    {"name": "百度贴吧热议", "url": "https://tieba.baidu.com/hottopic/browse/topicList", "parse": parse_tieba},
    {"name": "新浪滚动新闻", "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=50&page=1", "parse": parse_sina},
    {"name": "IT之家新闻", "url": "https://api.ithome.com/json/newslist/news", "parse": parse_ithome_news},
    {"name": "36氪热榜", "url": "https://v2.xxapi.cn/api/hot36kr", "parse": parse_36kr},
    {"name": "IT之家滚动", "url": "http://api.xcvts.cn/api/hotlist/ithome", "parse": parse_xcvts_ithome},
    {"name": "东方财富快讯", "url": "http://api.xcvts.cn/api/hotlist/eastmoney", "parse": parse_eastmoney},
    {"name": "微博热搜", "url": "https://apiserver.luoying.work/api/weibo-hot", "parse": parse_luoying, "rate_limit": True},
    {"name": "聚合数据新闻头条", "url": f"https://v.juhe.cn/toutiao/index?key={JUHE_NEWS_API_KEY}&type=top", "parse": parse_juhe},
    {"name": "知乎全网搜索", "url": zhihu_url, "headers": {"Authorization": f"Bearer {ZHIHU_ACCESS_SECRET}", "X-Request-Timestamp": str(int(time.time())), "Content-Type": "application/json"}, "parse": parse_zhihu},
    {"name": "百度热搜(聚合)", "url": "https://apiserver.luoying.work/api/baidu-hot", "parse": parse_luoying, "rate_limit": True},
]

# ---------- 权威官媒/通讯社（接口地址从 .env 读取） ----------
# 人民网旧 RSS 自 2025-06-05 起停止更新（静态存档），已改为频道页 HTML + URL 日期过滤
PEOPLE_FRESH_DAYS = int(os.getenv("PEOPLE_FRESH_DAYS", "1"))
_PEOPLE_POLITICS = os.getenv("PEOPLE_POLITICS_URL",
                             "http://politics.people.com.cn/GB/1024/index.html")
_PEOPLE_WORLD = os.getenv("PEOPLE_WORLD_URL", "http://world.people.com.cn/")
_XINHUA_HOME = os.getenv("XINHUA_HOME", "http://www.news.cn/")
_XINHUA_WORLD = os.getenv("XINHUA_WORLD", "http://www.news.cn/world/")
_CCTV_XWLB = os.getenv("CCTV_XWLB", "https://tv.cctv.com/lm/xwlb/")
_NEWSAPI_BASE = os.getenv("NEWSAPI_BASE", "https://newsapi.org/v2/everything")

OFFICIAL_SOURCES = [
    {"name": "人民日报·时政", "url": _PEOPLE_POLITICS, "kind": "text", "parse": parse_people_html},
    {"name": "人民日报·国际", "url": _PEOPLE_WORLD, "kind": "text", "parse": parse_people_html},
    {"name": "新华社·要闻", "url": _XINHUA_HOME, "kind": "text", "parse": parse_xinhua_html},
    {"name": "新华社·国际", "url": _XINHUA_WORLD, "kind": "text", "parse": parse_xinhua_html},
    {"name": "新闻联播", "url": _CCTV_XWLB, "kind": "text", "parse": parse_cctv_xwlb},
]
# 美联社经 NewsAPI.org 聚合（走迷雾通代理），key 留空时跳过
# 注：路透社在 NewsAPI 免费版几乎无索引（NewsAPI 后端同样被其 DataDome 反爬拦截），故不接入
if NEWSAPI_KEY:
    OFFICIAL_SOURCES += [
        {"name": "美联社 AP",
         "url": f"{_NEWSAPI_BASE}?domains=apnews.com&sortBy=publishedAt&pageSize=50&apiKey={NEWSAPI_KEY}",
         "kind": "json", "parse": parse_newsapi, "proxy": True},
    ]
SOURCES.extend(OFFICIAL_SOURCES)


def collect_report():
    """抓取所有数据源，返回报告文本。"""
    lines = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append("新闻抓取报告")
    lines.append("生成时间: " + now)
    lines.append("=" * 60)
    lines.append("")

    for src in SOURCES:
        name = src["name"]
        lines.append("【" + name + "】")
        try:
            data = fetch_source(src)
            items = src["parse"](data)
            lines.append(f"（共 {len(items)} 条）")
            for i, it in enumerate(items, 1):
                lines.append(f"{i}. {it['title']}")
                if it.get("url"):
                    lines.append(f"   {it['url']}")
                if it.get("meta"):
                    lines.append(f"   {it['meta']}")
        except Exception as e:
            lines.append(f"[请求失败] {type(e).__name__}: {e}")
        lines.append("")

    return "\n".join(lines)


def save_snapshot(text):
    """把报告保存为带时间戳的 txt，返回绝对路径。"""
    filename = "news_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
    path = os.path.join(BASE_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def send_email_with_attachment(path):
    """把 txt 快照作为附件发送邮件。"""
    if not (MAIL_FROM and MAIL_AUTH_CODE and MAIL_TO):
        print("[mail] 邮件配置不完整，跳过发送", flush=True)
        return False
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart()
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    msg["Subject"] = f"每日新闻快照 {date_str}"

    msg.attach(MIMEText("今日新闻快照见附件。", "plain", "utf-8"))

    with open(path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=os.path.basename(path))
    msg.attach(part)

    try:
        try:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30,
                                      context=ssl.create_default_context())
        except Exception:
            server = smtplib.SMTP(SMTP_HOST, 587, timeout=30)
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        server.login(MAIL_FROM, MAIL_AUTH_CODE)
        server.sendmail(MAIL_FROM, [MAIL_TO], msg.as_string())
        server.quit()
        print(f"[mail] 已发送到 {MAIL_TO}: {os.path.basename(path)}", flush=True)
        return True
    except Exception as e:
        print(f"[mail] 发送失败: {type(e).__name__}: {e}", flush=True)
        return False


def main():
    text = collect_report()
    print(text)
    path = save_snapshot(text)
    print("\n已保存到 " + path)
    send_email_with_attachment(path)


if __name__ == "__main__":
    main()