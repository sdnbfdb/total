#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MediaCrawler cookie 登录采集入口。
用法: python run_mc.py <平台> <关键词> [条数]
平台: xhs | dy | ks | bili | wb | tieba | zhihu
示例: python run_mc.py zhihu "重庆旅游" 5
"""
import json
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MC = os.path.join(HERE, "MediaCrawler")
COOKIES = json.load(open(os.path.join(HERE, "data-samples", "cookies_media.json"), encoding="utf-8"))

PLATFORM_KEY = {
    "xhs": "xhs", "dy": "douyin", "ks": "kuaishou", "bili": "bilibili",
    "wb": "weibo", "tieba": "tieba", "zhihu": "zhihu",
}

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    platform = sys.argv[1]
    keywords = sys.argv[2]
    limit = sys.argv[3] if len(sys.argv) > 3 else "5"
    key = PLATFORM_KEY.get(platform)
    if not key:
        print("未知平台:", platform)
        sys.exit(1)
    cookie = COOKIES[key]["cookie"]
    if len(cookie) < 30:
        print(f"[{platform}] cookie 过短（可能未登录），仍尝试运行")

    cmd = [
        os.path.join(MC, ".venv", "Scripts", "python.exe"), "main.py",
        "--platform", platform,
        "--lt", "cookie",
        "--cookies", cookie,
        "--keywords", keywords,
        "--crawler_max_notes_count", limit,
        "--max_concurrency_num", "1",
        "--save_data_option", "json",
    ]
    print("运行:", " ".join(cmd[:8]), "...")
    # NODE_OPTIONS 注入的 shim 路径会带崩 Playwright 的 Node 驱动，必须清除；
    # TMP 指向可写目录，规避沙箱对 AppData\Local\Temp 的 EPERM
    env = {k: v for k, v in os.environ.items()
           if k not in ("NODE_OPTIONS", "NODE_REQUIRES", "ELECTRON_RUN_AS_NODE")}
    tmp = os.path.join(HERE, "tmp")
    os.makedirs(tmp, exist_ok=True)
    env["TMP"] = env["TEMP"] = tmp
    r = subprocess.run(cmd, cwd=MC, env=env)
    sys.exit(r.returncode)

if __name__ == "__main__":
    main()
