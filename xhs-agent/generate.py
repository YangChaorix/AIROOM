#!/usr/bin/env python3
"""
generate.py - 调用 Anthropic API 根据热点生成小红书文案
用法：从 stdin 读取热点 JSON，输出文案 JSON

输入（来自 xhs_tool.py trending 的输出）：
{
  "status": "ok",
  "trending": [{"title": ".."likes": "...", "tags": [...]}]
}

输出：
{
  "title": "生成的标题",
  "content": "生成的正文",
  "tags": ["标签1", "标签2", "标签3"]
}
"""

import sys
import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config" / "settings.json"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def generate(trending_data: list, config: dict) -> dict:
    import anthropic

    style = config["account"]["style"]
    tone = config["account"]["tone"]
    ref_tags = ", ".join(config["account"]["tags"])

    # 取前 5 条热点作为参考
    top = trending_data[:5]
    trending_text = "\n".join(
        f"- {item['title']}（点赞：{item['likes']}，标签：{', '.join(item['tags'])}）"
        for item in top
    )

    prompt = f"""你是一个小红书内容运营专家。

账号定位：{style}
文案风格：{tone}
常用标签参考：{ref_tags}

今日平台热点（供参考，不必照抄）：
{trending_text}

请根据以上信息，生成一篇适合发布的小红书笔记。要求：
1. 标题吸引眼球，15字以内，可带emoji
2. 正文真实有温度，200-400字，段落清晰
3. 结尾引导互动（如"你们呢？"）
4. 给出 3-5 个相关标签（不带#）

请严格按以下 JSON 格式输出，不要有其他内容：
{{
  "title": "标题",
  "content": "正文",
  "tags": ["标签1", "标签2", "标签3"]
}}"""

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # 提取 JSON（防止模型输出多余内容）
    start = raw.find("{")
    end = raw.rfind("}") + 1
    return json.loads(raw[start:end])


if __name__ == "__main__":
    try:
        input_data = json.load(sys.stdin)
        if input_data.get("status") != "ok":
            print(json.dumps({"status": "error", "message": "热点数据异常"}, ensure_ascii=False))
            sys.exit(1)

        config = load_config()
        result = generate(input_data["trending"], config)
        print(json.dumps({"status": "ok", **result}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)
