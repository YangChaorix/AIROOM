#!/usr/bin/env python3
"""
run.py - 主入口，串联完整发布流程
流程：
  1. 抓取今日热点（xhs_tool.py trending）
  2. 生成文案（generate.py）
  3. 发布笔记（xhs_tool.py publish）
  4. 记录日志

用法：
  python run.py              # 正常执行
  python run.py --dry-run    # 仅生成文案，不发布
"""

import sys
import json
import subprocess
import logging
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
PYTHON = str(BASE_DIR / ".venv" / "bin" / "python")

# 日志配置
log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def run_cmd(cmd: list, stdin_data: str = None) -> dict:
    """执行子命令，返回解析后的 JSON 结果"""
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and not result.stdout:
        return {"status": "error", "message": result.stderr.strip()}
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"status": "error", "message": f"输出解析失败: {result.stdout[:200]}"}


def main():
    dry_run = "--dry-run" in sys.argv
    log.info("=" * 50)
    log.info(f"xhs-agent 开始运行 {'[DRY RUN]' if dry_run else ''}")
    log.info("=" * 50)

    # Step 1: 抓取热点
    log.info("Step 1: 抓取今日热点...")
    trending_result = run_cmd([PYTHON, str(BASE_DIR / "xhs_tool.py"), "trending"])
    if trending_result.get("status") != "ok":
        log.error(f"热点抓取失败: {trending_result.get('message')}")
        sys.exit(1)
    log.info(f"获取到 {len(trending_result.get('trending', []))} 条热点")

    # Step 2: 生成文案
    log.info("Step 2: 生成文案...")
    copy_result = run_cmd(
        [PYTHON, str(BASE_DIR / "generate.py")],
        stdin_data=json.dumps(trending_result)
    )
    if copy_result.get("status") != "ok":
        log.error(f"文案生成失败: {copy_result.get('message')}")
        sys.exit(1)

    title = copy_result.get("title", "")
    content = copy_result.get("content", "")
    tags = copy_result.get("tags", [])
    log.info(f"生成标题：{title}")
    log.info(f"生成标签：{tags}")

    if dry_run:
        log.info("[DRY RUN] 跳过发布，文案如下：")
        log.info(f"标题：{title}")
        log.info(f"正文：\n{content}")
        log.info(f"标签：{tags}")
        print(json.dumps({"status": "dry_run", "title": title, "content": content, "tags": tags}, ensure_ascii=False))
        return

    # Step 3: 发布笔记
    log.info("Step 3: 发布笔记...")
    publish_payload = json.dumps({
        "title": title,
        "content": content,
        "tags": tags,
    })
    publish_result = run_cmd(
        [PYTHON, str(BASE_DIR / "xhs_tool.py"), "publish"],
        stdin_data=publish_payload
    )
    if publish_result.get("status") != "ok":
        log.error(f"发布失败: {publish_result.get('message')}")
        sys.exit(1)

    note_url = publish_result.get("url", "")
    log.info(f"✅ 发布成功！笔记链接：{note_url}")
    print(json.dumps({"status": "ok", "url": note_url, "title": title}, ensure_ascii=False))


if __name__ == "__main__":
    main()
