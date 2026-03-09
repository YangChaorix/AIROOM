#!/usr/bin/env python3
"""
xhs_tool.py - 小红书操作封装
命令：
  trending              获取首页热点（返回 JSON）
  publish               发布笔记（从 stdin 读取 JSON）
  analytics             获取账号数据

凭证位置：~/.openclaw/credentials/xhs.json
  { "a1": "...", "web_session": "..." }
"""

import sys
import json
from pathlib import Path

CRED_PATH = Path.home() / ".openclaw" / "credentials" / "xhs.json"


def load_credentials():
    if not CRED_PATH.exists():
        _exit_error(f"凭证文件不存在: {CRED_PATH}")
    with open(CRED_PATH) as f:
        creds = json.load(f)
    a1 = creds.get("a1", "")
    web_session = creds.get("web_session", "")
    if not a1 or a1.startswith("PLACEHOLDER"):
        _exit_error("请先在 xhs.json 中填写真实的 a1 cookie")
    cookie = f"a1={a1}; web_session={web_session}"
    return a1, cookie


def make_client(a1, cookie):
    from xhs import XhsClient
    from xhs.help import sign as _sign

    def sign_fn(uri, data=None, a1=a1, web_session=""):
        return _sign(uri, data, a1=a1)

    return XhsClient(cookie=cookie, sign=sign_fn)


def _exit_error(msg):
    print(json.dumps({"status": "error", "message": msg}, ensure_ascii=False))
    sys.exit(1)


def _ok(data):
    print(json.dumps({"status": "ok", **data}, ensure_ascii=False))


def cmd_trending():
    """抓取职场方向热点，返回 top 10"""
    try:
        from xhs.core import FeedType
        a1, cookie = load_credentials()
        client = make_client(a1, cookie)
        resp = client.get_home_feed(FeedType.CAREER)
        items = resp.get("items", [])[:10]
        results = []
        for item in items:
            note = item.get("note_card", {})
            results.append({
                "title": note.get("display_title", ""),
                "likes": note.get("interact_info", {}).get("liked_count", "0"),
                "tags": [t.get("name", "") for t in note.get("tag_list", [])],
            })
        _ok({"trending": results})
    except Exception as e:
        _exit_error(str(e))


def cmd_publish():
    """
    从 stdin 读取 JSON 发布笔记
    输入格式：
    {
      "title": "标题",
      "content": "正文",
      "tags": ["标签1", "标签2"],
      "image_paths": ["/path/to/img.jpg"]   // 可选
    }
    """
    try:
        a1, cookie = load_credentials()
        client = make_client(a1, cookie)

        payload = json.load(sys.stdin)
        title = payload.get("title", "")
        content = payload.get("content", "")
        tags = payload.get("tags", [])
        image_paths = payload.get("image_paths", [])

        tag_str = " ".join(f"#{t}" for t in tags)
        full_content = f"{content}\n{tag_str}".strip()

        if image_paths:
            token_list = []
            for path in image_paths:
                permit = client.get_upload_files_permit("image", 1)
                uploaded = client.upload_file(permit, path)
                token_list.append(uploaded)
            result = client.create_image_note(title, full_content, token_list)
        else:
            result = client.create_note(title, full_content)

        note_id = result.get("note_id", "")
        _ok({
            "note_id": note_id,
            "url": f"https://www.xiaohongshu.com/explore/{note_id}"
        })
    except Exception as e:
        _exit_error(str(e))


def cmd_analytics():
    """获取账号粉丝数、获赞数、笔记数"""
    try:
        a1, cookie = load_credentials()
        client = make_client(a1, cookie)

        info = client.get_self_info()
        user = info.get("data", {}).get("userInfo", {})
        interactions = user.get("interactions", [])

        _ok({
            "analytics": {
                "nickname": user.get("nickname", ""),
                "followers": next((i["count"] for i in interactions if i["type"] == "fans"), "0"),
                "likes": next((i["count"] for i in interactions if i["type"] == "liked"), "0"),
                "notes": next((i["count"] for i in interactions if i["type"] == "note"), "0"),
            }
        })
    except Exception as e:
        _exit_error(str(e))


COMMANDS = {
    "trending": cmd_trending,
    "publish": cmd_publish,
    "analytics": cmd_analytics,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"用法: python xhs_tool.py [{' | '.join(COMMANDS)}]")
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
