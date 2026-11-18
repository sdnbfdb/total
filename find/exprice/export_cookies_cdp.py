import asyncio, json, time, sys, urllib.request
import websockets

OUT = "C:/Users/sanjin/Desktop/find/exprice/data-samples/edge_cookies_full.json"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9223

async def main():
    for attempt in range(15):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=3))
            break
        except Exception:
            await asyncio.sleep(1)
    else:
        print("CDP 端口未就绪"); sys.exit(1)

    page = next((t for t in targets if t.get("type") == "page"), None)
    if not page:
        print("无页面目标"); sys.exit(1)
    print("连接:", page.get("url"))

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=50*1024*1024) as ws:
        msg_id = 0
        async def send(method, params=None):
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == msg_id:
                    return m.get("result", {})

        r = await send("Storage.getCookies")
        cookies = r.get("cookies", [])
        print("总 cookie:", len(cookies))

        # 转为 name=value 字符串格式（按域名分组）
        by_domain = {}
        for c in cookies:
            by_domain.setdefault(c["domain"], []).append(c)

        target_kw = ("douyin", "bilibili", "zhihu", "tieba", "xiaohongshu", "weibo", "kuaishou")
        tcount = {d: len(v) for d, v in by_domain.items() if any(k in d for k in target_kw)}
        print("目标平台:", tcount if tcount else "(无)")

        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=1)
        print("已保存:", OUT)

        # 快速验证 B 站登录态
        await send("Page.enable")
        await send("Page.navigate", {"url": "https://api.bilibili.com/x/web-interface/nav"})
        await asyncio.sleep(3)
        r = await send("Runtime.evaluate", {"expression": "document.body.innerText.slice(0, 300)", "returnByValue": True})
        text = r.get("result", {}).get("value", "")
        try:
            d = json.loads(text[text.index("{"):])
            print("B站 isLogin:", d.get("data", {}).get("isLogin"), "uname:", d.get("data", {}).get("uname"))
        except Exception:
            print("B站返回:", text[:200])

asyncio.run(main())
