# -*- coding: utf-8 -*-
"""M7（可选）· LLM 叙事弧线/摘要（构建文档 §7.7）；失败回退规则摘要，不阻塞。"""
import os
import json
import urllib.request


def narrate(event, timeline_summary):
    """
    优先用 LLM 生成脉络综述（.env: LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）；
    未配置或失败 → 返回规则摘要。
    """
    key = os.getenv("LLM_API_KEY", "")
    if not key:
        return timeline_summary
    base = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    lines = [f"{it['date']} {it['source']} {it['title']}" for it in
             (event.get("timeline") or [])[:15]]
    prompt = ("请用一两句话概括以下新闻报道的事件演进脉络（中文，直接给结论）：\n"
              + "\n".join(lines))
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 120,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip() or timeline_summary
    except Exception:
        return timeline_summary
