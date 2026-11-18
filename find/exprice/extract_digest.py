"""从 MediaCrawler 采集数据中提取「英语长难句」主题的摘要
- 过滤掉旧测试数据（重庆旅游）
- 识别：同样症状的人（单词认识但长句读不懂）+ 他们的解决方法
输出到 tmp/digest_<平台>.md
"""
import json, re, os

BASE = "C:/Users/sanjin/Desktop/find/exprice/MediaCrawler/data"
OUT = "C:/Users/sanjin/Desktop/find/exprice/tmp"

TOPIC = re.compile(r"长难句|长句|句子.*(读不懂|看不懂|翻译|读不出|懵)|(读不懂|看不懂|翻译|读不出).*句子|单词.*(认识|会|背|记住|没问题)|语法|主谓宾|定语从句|状语从句|主干|意群|拆句|精读")
SYMPTOM = re.compile(r"单词(认识|会|都?记得|没问题|背了|背得)|(认识|会)单词|单词.{0,6}(但|可是|就是)|句子.{0,8}(读不懂|看不懂|不会|翻译不出|读不出|一长|懵)|(读不懂|看不懂|不会翻译|翻译不了).{0,6}(句子|长句|长难句)|长难句.{0,6}(读不懂|看不懂|不会|困难|头疼|害怕)")
METHOD = re.compile(r"语法|主谓宾|主干|从句|意群|拆|精读|翻译(练习|训练)|多读|每天|坚持|刷题|背(句型|课文|作文)|新概念|新一|新二|新三|阅读|语感|结构|断句|成分|学会(划分|找)|笔记|框架|练")

def load(platform):
    c = json.load(open(f"{BASE}/{platform}/json/search_contents_2026-11-18.json", encoding="utf-8"))
    m = json.load(open(f"{BASE}/{platform}/json/search_comments_2026-11-18.json", encoding="utf-8"))
    return c, m

def is_topic(text):
    return bool(TOPIC.search(text or ""))

def digest(platform, name):
    contents, comments = load(platform)
    # 按主题过滤帖子（排除旧测试数据）
    rel = [p for p in contents if is_topic((p.get("title") or "") + (p.get("content") or ""))]
    rel_ids = {str(p.get("note_id") or p.get("aweme_id") or p.get("video_id") or p.get("content_id") or p.get("tieba_id") or "") for p in rel}
    # 评论：挂在相关帖子下 或 文本本身含主题词
    rel_comments = []
    for c in comments:
        cid = str(c.get("content_id") or c.get("note_id") or c.get("aweme_id") or c.get("video_id") or "")
        text = c.get("content") or ""
        if cid in rel_ids or is_topic(text):
            rel_comments.append(c)

    lines = [f"# {name} 摘要（主题帖 {len(rel)} 篇 / 相关评论 {len(rel_comments)} 条）", ""]
    lines.append("## 帖子")
    for p in rel:
        title = p.get("title") or ""
        content = (p.get("content") or "").replace("\n", " ")[:280]
        likes = p.get("liked_count") or p.get("like_count") or ""
        author = (p.get("user") or {}).get("nickname") or p.get("user_nickname") or p.get("author") or ""
        if isinstance(author, dict):
            author = author.get("nickname", "")
        lines.append(f"### [{author}] {title[:60]} (赞{likes})")
        lines.append(content)
        lines.append("")

    lines.append("## 评论（含症状/方法描述）")
    for c in rel_comments:
        text = (c.get("content") or "").replace("\n", " ")[:180]
        author = c.get("user_nickname") or ""
        mark = []
        if SYMPTOM.search(text): mark.append("症状")
        if METHOD.search(text): mark.append("方法")
        lines.append(f"- ({','.join(mark) or '其他'}) [{author}] {text}")
    path = f"{OUT}/digest_{platform}.md"
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    n_sym = sum(1 for c in rel_comments if SYMPTOM.search(c.get("content") or ""))
    n_meth = sum(1 for c in rel_comments if METHOD.search(c.get("content") or ""))
    print(f"{platform}: 帖子{len(rel)} 评论{len(rel_comments)} (症状{n_sym}/方法{n_meth}) -> {path}")

for plat, name in [("xhs", "小红书"), ("zhihu", "知乎"), ("bili", "B站"), ("douyin", "抖音")]:
    try:
        digest(plat, name)
    except Exception as e:
        print(f"{plat} 出错: {e}")
