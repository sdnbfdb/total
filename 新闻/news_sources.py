# -*- coding: utf-8 -*-
"""
新闻数据源汇总脚本
收录所有"已验证可用"的接口地址，密钥从 .env 读取。
直接运行本脚本可打印全部接口清单，也可被 app.py 导入复用。
"""
import os
import datetime


def load_env(path=".env"):
    """极简 .env 读取，避免额外引入第三方依赖。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()

JUHE_NEWS_API_KEY = os.getenv("JUHE_NEWS_API_KEY", "")
ZHIHU_ACCESS_SECRET = os.getenv("ZHIHU_ACCESS_SECRET", "")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

SOURCES = [
    # ---------- 免费直连接口（无需密钥） ----------
    {
        "name": "百度热搜",
        "method": "GET",
        "url": "https://top.baidu.com/api/board?platform=wise&tab=realtime",
        "remark": "无需密钥",
    },
    {
        "name": "今日头条热榜",
        "method": "GET",
        "url": "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
        "remark": "无需密钥",
    },
    {
        "name": "百度贴吧热议",
        "method": "GET",
        "url": "https://tieba.baidu.com/hottopic/browse/topicList",
        "remark": "无需密钥",
    },
    {
        "name": "新浪滚动新闻",
        "method": "GET",
        "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=50&page=1",
        "remark": "无需密钥",
    },
    {
        "name": "IT之家新闻",
        "method": "GET",
        "url": "https://api.ithome.com/json/newslist/news",
        "remark": "无需密钥",
    },
    {
        "name": "36氪热榜（聚合）",
        "method": "GET",
        "url": "https://v2.xxapi.cn/api/hot36kr",
        "remark": "返回 data[]，字段 itemId/publishTime/templateMaterial{authorName,widgetTitle,widgetImage,statPraise,statRead}",
    },
    {
        "name": "IT之家滚动（聚合）",
        "method": "GET",
        "url": "http://api.xcvts.cn/api/hotlist/ithome",
        "remark": "返回 data[]，字段 id/category/title/link/time，共 50 条",
    },
    {
        "name": "东方财富快讯（聚合）",
        "method": "GET",
        "url": "http://api.xcvts.cn/api/hotlist/eastmoney",
        "remark": "返回 data[]，字段 id/time/title/content/url/mobileUrl，共 50 条",
    },
    # ---------- 第三方热榜聚合（无需密钥，匿名限流约 1 次/分钟） ----------
    {
        "name": "微博热搜（聚合）",
        "method": "GET",
        "url": "https://apiserver.luoying.work/api/weibo-hot",
        "remark": "返回 data.list[]，字段 rank/title/heat/label/url；匿名限流约 1 次/分钟",
    },
    {
        "name": "百度热搜（聚合）",
        "method": "GET",
        "url": "https://apiserver.luoying.work/api/baidu-hot",
        "remark": "匿名限流约 1 次/分钟（浮动），建议控制请求频率",
    },
    # ---------- 需密钥接口 ----------
    {
        "name": "聚合数据·新闻头条",
        "method": "GET",
        "url": f"https://v.juhe.cn/toutiao/index?key={JUHE_NEWS_API_KEY}&type=top",
        "remark": "type 可选 guonei/guoji/keji/tiyu/yule 等，默认 top；key 来自 .env",
    },
    {
        "name": "知乎·全网搜索",
        "method": "GET",
        "url": "https://developer.zhihu.com/api/v1/content/global_search?Query=关键词&Count=10",
        "headers": {
            "Authorization": f"Bearer {ZHIHU_ACCESS_SECRET}",
            "X-Request-Timestamp": "<秒级时间戳>",
            "Content-Type": "application/json",
        },
        "remark": "secret 放在 Authorization 头，不是 URL；时间戳需传当前秒级值",
    },
    # ---------- 权威官媒/通讯社（接口地址从 .env 读取） ----------
    {
        "name": "人民日报·时政",
        "method": "GET(HTML)",
        "url": os.getenv("PEOPLE_POLITICS_URL", "http://politics.people.com.cn/GB/1024/index.html"),
        "remark": "人民网时政频道页，按 URL 日期只取当日/近日文章；旧 RSS 自 2025-06-05 停更已弃用",
    },
    {
        "name": "人民日报·国际",
        "method": "GET(HTML)",
        "url": os.getenv("PEOPLE_WORLD_URL", "http://world.people.com.cn/"),
        "remark": "人民网国际频道页，按 URL 日期只取当日/近日文章；无需密钥",
    },
    {
        "name": "新华社·要闻",
        "method": "GET(HTML)",
        "url": os.getenv("XINHUA_HOME", "http://www.news.cn/"),
        "remark": "新华网首页要闻，解析标题列表，无需密钥",
    },
    {
        "name": "新华社·国际",
        "method": "GET(HTML)",
        "url": os.getenv("XINHUA_WORLD", "http://www.news.cn/world/"),
        "remark": "新华网国际频道页，解析标题列表，无需密钥",
    },
    {
        "name": "新闻联播",
        "method": "GET(HTML)",
        "url": os.getenv("CCTV_XWLB", "https://tv.cctv.com/lm/xwlb/"),
        "remark": "央视网栏目页，每天 19:00 后更新当天条目，无需密钥",
    },
    {
        "name": "美联社 AP",
        "method": "GET(JSON)",
        "url": f"{os.getenv('NEWSAPI_BASE', 'https://newsapi.org/v2/everything')}?domains=apnews.com&sortBy=publishedAt&pageSize=50&apiKey={'<NEWSAPI_KEY>' if not NEWSAPI_KEY else '***'}",
        "remark": "经 NewsAPI.org 聚合（走迷雾通代理），需在 .env 填 NEWSAPI_KEY；免费版约 24 小时延迟",
    },
]


def render():
    lines = []
    for s in SOURCES:
        lines.append(f"[{s['name']}]  {s['method']}")
        lines.append(f"  {s['url']}")
        if s.get("headers"):
            lines.append(f"  headers: {s['headers']}")
        lines.append(f"  备注: {s['remark']}")
        lines.append("")
    return "\n".join(lines)


def main():
    text = render()
    print(text)
    filename = "news_sources_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"已保存到 {filename}")


if __name__ == "__main__":
    main()