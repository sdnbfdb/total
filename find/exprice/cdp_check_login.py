import asyncio, json, sys
import websockets

async def main():
    # 1. 列出目标
    import urllib.request
    targets = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json/list"))
    page = next((t for t in targets if t.get("type") == "page"), None)
    if not page:
        print("没有页面目标"); return
    print("连接目标:", page.get("url"), page.get("title"))

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=20*1024*1024) as ws:
        msg_id = 0
        async def send(method, params=None):
            nonlocal msg_id
            msg_id += 1
            await ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == msg_id:
                    return m.get("result", {})

        # 总 cookie 数
        r = await send("Storage.getCookies")
        cookies = r.get("cookies", [])
        print("Storage.getCookies 总数:", len(cookies))
        from collections import Counter
        doms = Counter(c["domain"] for c in cookies)
        target_kw = ("douyin", "bilibili", "zhihu", "tieba", "xiaohongshu", "weibo", "kuaishou")
        tcount = {d: n for d, n in doms.items() if any(k in d for k in target_kw)}
        print("目标平台域名:", tcount if tcount else "(无)")

        # 导航到B站验证登录态
        await send("Page.enable")
        await send("Page.navigate", {"url": "https://api.bilibili.com/x/web-interface/nav"})
        await asyncio.sleep(3)
        r = await send("Runtime.evaluate", {
            "expression": "document.body.innerText.slice(0, 400)",
            "returnByValue": True,
        })
        text = r.get("result", {}).get("value", "")
        print("B站nav返回:", text[:300])
        try:
            d = json.loads(text[text.index("{"):])
            print("=> isLogin:", d.get("data", {}).get("isLogin"), "| uname:", d.get("data", {}).get("uname"))
        except Exception:
            pass

asyncio.run(main())
