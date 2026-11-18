"""从小红书持久化浏览器配置中提取登录 cookie，更新 cookies_media.json"""
import asyncio, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "MediaCrawler"))

async def main():
    from playwright.async_api import async_playwright

    user_data_dir = os.path.join(HERE, "MediaCrawler", "browser_data", "xhs_user_data_dir")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=True,
            channel="chrome",
        )
        cookies = await ctx.cookies()
        await ctx.close()

    jar = {c["name"]: c["value"] for c in cookies if "xiaohongshu" in c.get("domain", "") or "rednote" in c.get("domain", "")}
    print("提取到", len(jar), "个小红书 cookie")
    print("关键 cookie:", {k: jar[k][:24] + "..." for k in ["web_session", "a1", "webId", "xsecappid"] if k in jar})

    if "web_session" not in jar:
        print("!!! 未找到 web_session，不更新"); return

    cookie_str = "; ".join(f"{k}={v}" for k, v in jar.items())
    path = os.path.join(HERE, "data-samples", "cookies_media.json")
    data = json.load(open(path, encoding="utf-8"))
    data["xhs"] = {"len": len(cookie_str), "cookie": cookie_str}
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("cookies_media.json 已更新, xhs cookie 长度:", len(cookie_str))

asyncio.run(main())
