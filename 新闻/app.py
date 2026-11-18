# -*- coding: utf-8 -*-
"""
基于 Flask 的新闻聚合服务，常驻 5000 端口。
每天 15:00 自动触发抓取，生成带时间戳的 txt 快照。
"""
import datetime
import urllib.parse

from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

from fetch_news import SOURCES, fetch_source, collect_report, save_snapshot, send_email_with_attachment

app = Flask(__name__)

# 密钥类查询参数名，/sources 端点会把这些参数的值替换为 ***
SECRET_PARAMS = {"key", "secret", "token", "access_token", "apikey", "api_key", "auth"}


def public_url(url):
    """去掉 URL 中的密钥类查询参数，避免 /sources 端点泄露凭据。"""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    masked = [(k, "***" if k.lower() in SECRET_PARAMS else v) for k, v in pairs]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(masked)))


@app.route("/")
def home():
    return jsonify({
        "service": "新闻聚合服务",
        "endpoints": {
            "/sources": "可用数据源列表",
            "/news": "抓取新闻（可加 ?source=名称 指定单个源）",
            "/generate": "抓取并生成 txt 快照文件",
        },
    })


@app.route("/sources")
def sources():
    return jsonify([
        {"name": s["name"], "url": public_url(s["url"])} for s in SOURCES
    ])


@app.route("/news")
def news():
    name = request.args.get("source")
    targets = [s for s in SOURCES if s["name"] == name] if name else SOURCES
    if name and not targets:
        return jsonify({"error": "未找到数据源: " + name}), 404

    results = []
    for s in targets:
        try:
            data = fetch_source(s)
            items = s["parse"](data)
            results.append({"name": s["name"], "count": len(items), "items": items})
        except Exception as e:
            results.append({"name": s["name"], "error": f"{type(e).__name__}: {e}"})
    return jsonify(results)


@app.route("/generate")
def generate():
    path = save_snapshot(collect_report())
    return jsonify({"status": "ok", "file": path})


# ---------- 事件脉络分析端点（构建文档 §12） ----------

def _analysis_store():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis"))
    import store as analysis_store
    return analysis_store


@app.route("/events")
def events_list():
    """事件列表（按 多源佐证 × 出现次数 排序，支持 ?category= / ?phase= 筛选）。"""
    data = _analysis_store().load_events()
    if not data:
        return jsonify({"error": "事件库尚未生成，请先运行 python analysis/analyze.py"}), 404
    cat = request.args.get("category")
    ph = request.args.get("phase")
    items = data["events"]
    if cat:
        items = [e for e in items if e.get("category") == cat]
    if ph:
        items = [e for e in items if e.get("phase") == ph]
    return jsonify({
        "generated_at": data.get("generated_at"),
        "count": len(items),
        "events": [{
            "event_id": e["event_id"], "name": e["name"], "category": e.get("category"),
            "phase": e.get("phase"), "count": e["count"],
            "first_seen": e["first_seen"], "last_seen": e["last_seen"],
            "source_count": e["source_count"],
        } for e in items[:200]],
    })


@app.route("/events/<event_id>")
def event_detail(event_id):
    """单事件脉络：时间线/阶段/突发/相关事件。"""
    data = _analysis_store().load_events()
    if not data:
        return jsonify({"error": "事件库尚未生成"}), 404
    for e in data["events"]:
        if e["event_id"] == event_id:
            return jsonify(e)
    return jsonify({"error": "未找到事件: " + event_id}), 404


@app.route("/graph")
def graph_route():
    """知识图谱 JSON：节点（事件）+ 相关边 + 演进顺延边 + 故事链。"""
    import json
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "knowledge_graph.json")
    if not os.path.exists(p):
        return jsonify({"error": "图谱尚未生成，请先运行 python analysis/analyze.py"}), 404
    with open(p, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/report")
def report_route():
    """生成/返回最新脉络报告路径。"""
    import subprocess, sys
    try:
        out = subprocess.check_output(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "analysis", "analyze.py")],
            timeout=1800, stderr=subprocess.STDOUT)
    except Exception:
        out = b""
    md_path, html_path = None, None
    reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    if os.path.isdir(reports_dir):
        files = sorted(f for f in os.listdir(reports_dir) if f.endswith((".md", ".html")))
        for f in files:
            p = os.path.join(reports_dir, f)
            if f.endswith(".md") and (md_path is None or p > md_path):
                md_path = p
            if f.endswith(".html") and (html_path is None or p > html_path):
                html_path = p
    return jsonify({"status": "ok", "report_md": md_path, "report_html": html_path})


def scheduled_snapshot():
    """每天 15:00 自动抓取、生成 txt 快照并发送邮件，随后增量更新事件脉络库。"""
    try:
        path = save_snapshot(collect_report())
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 已生成新闻快照: {path}", flush=True)
        send_email_with_attachment(path)
    except Exception as e:
        print(f"[scheduler] 生成快照失败: {type(e).__name__}: {e}", flush=True)
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis"))
        from analyze import incremental
        incremental()
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 事件脉络库已增量更新", flush=True)
    except Exception as e:
        print(f"[scheduler] 事件分析失败: {type(e).__name__}: {e}", flush=True)


import os, glob

def _already_done_today():
    """Check if today news snapshot already exists."""
    today = datetime.datetime.now().strftime("%Y%m%d")
    pattern = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"news_{today}_*.txt")
    return len(glob.glob(pattern)) > 0

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
scheduler.add_job(
    scheduled_snapshot, "cron", hour=15, minute=0,
    id="daily_news_snapshot",
    misfire_grace_time=3600,
)
scheduler.start()

# If past 15:00 and today not done, run immediately
if datetime.datetime.now().hour >= 15 and not _already_done_today():
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Today snapshot missing, running catchup...", flush=True)
    scheduler.add_job(scheduled_snapshot, "date", id="startup_catchup")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)