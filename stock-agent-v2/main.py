"""
stock-agent-v2 主入口

使用方式：
  python main.py --trigger-only    # 仅运行触发检测
  python main.py --event           # 触发 + 精筛（无复盘）
  python main.py --review          # 仅收盘复盘
  python main.py --schedule        # 启动定时任务（09:15触发+精筛，15:35复盘）
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import settings


def setup_logging():
    """
    初始化日志：
    - 控制台：INFO 级别，简洁格式
    - 文件：DEBUG 级别，完整格式，写入 logs/YYYY-MM-DD.log
    """
    today = datetime.now().strftime("%Y-%m-%d")
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{today}.log")

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 清除已有 handler（避免重复）
    root.handlers.clear()

    # 控制台 handler（INFO）
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(ch)

    # 文件 handler（DEBUG）
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(fh)

    # 抑制第三方库的 DEBUG 噪音
    for noisy in ["httpx", "httpcore", "urllib3", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(f"日志文件: {os.path.abspath(log_file)}")
    return log_file


setup_logging()
logger = logging.getLogger(__name__)


def _print_trigger_result(state: dict) -> None:
    tr = state.get("trigger_result") or {}
    print("\n" + "=" * 60)
    print("【触发Agent 输出】")
    print(f"日期：{tr.get('date', 'N/A')}")
    print(f"是否触发：{tr.get('has_triggers', False)}")
    triggers = tr.get("triggers", [])
    print(f"触发条目数：{len(triggers)}")
    for i, t in enumerate(triggers, 1):
        print(f"\n  [{i}] {t.get('type', '')} | 强度：{t.get('strength', '')}")
        print(f"      摘要：{t.get('summary', '')[:100]}...")
        print(f"      行业：{', '.join(t.get('industries', []))}")
        companies = t.get("companies", {})
        for cat, lst in companies.items():
            print(f"      {cat}：{', '.join(lst[:3]) if isinstance(lst[0], str) else str(lst[:3])}")
    if tr.get("error"):
        print(f"错误：{tr['error']}")
    print("=" * 60)


def _print_screener_result(state: dict) -> None:
    sr = state.get("screener_result") or {}
    if sr.get("skipped"):
        print("\n【精筛Agent】跳过（无触发信息）")
        return
    print("\n" + "=" * 60)
    print("【精筛Agent 输出 - Top 20】")
    top20 = sr.get("top20", [])
    for stock in top20:
        scores = stock.get("scores", {})
        total = stock.get("total_score", sum(v.get("score", 0) for v in scores.values()))
        print(f"\n  #{stock.get('rank', '?')} {stock.get('name', '')} ({stock.get('code', '')})"
              f" | 总分：{total}/18")
        print(f"      触发：{stock.get('trigger_reason', '')[:60]}")
        for dim, info in scores.items():
            print(f"      {dim}: {info.get('score', '?')}分 - {info.get('reason', '')[:40]}")
        print(f"      推荐：{stock.get('recommendation', '')[:120]}")
        print(f"      风险：{stock.get('risk', '')[:60]}")
    if sr.get("error"):
        print(f"错误：{sr['error']}")
    print("=" * 60)


def _print_review_result(state: dict) -> None:
    rr = state.get("review_result") or {}
    print("\n" + "=" * 60)
    print("【复盘Agent 输出】")
    if rr.get("error"):
        print(f"错误：{rr['error']}")
    else:
        print(rr.get("review_markdown", "（无内容）"))
    print("=" * 60)


def _save_results(state: dict) -> None:
    """将完整结果保存到 data/daily_push/"""
    data_dir = settings.agent.data_dir
    os.makedirs(data_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    # 保存复盘日报（markdown）
    review_result = state.get("review_result") or {}
    if review_result.get("review_markdown"):
        md_path = os.path.join(data_dir, f"{today}_review.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(review_result["review_markdown"])
        logger.info(f"复盘日报已保存: {md_path}")

    # 保存完整state（JSON）
    json_path = os.path.join(data_dir, f"{today}_full.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"完整结果已保存: {json_path}")


def cmd_trigger_only() -> None:
    """仅运行触发检测"""
    settings.validate()
    from graph.workflow import run_workflow
    logger.info("启动模式：仅触发检测")
    state = run_workflow(run_mode="trigger_only")
    _print_trigger_result(state)
    _save_results(state)


def cmd_event() -> None:
    """触发 + 精筛"""
    settings.validate()
    from graph.workflow import run_workflow
    logger.info("启动模式：触发 + 精筛")
    state = run_workflow(run_mode="full")
    _print_trigger_result(state)
    _print_screener_result(state)
    _save_results(state)


def cmd_review() -> None:
    """仅收盘复盘"""
    settings.validate()
    from graph.workflow import run_workflow
    logger.info("启动模式：仅复盘")
    state = run_workflow(run_mode="review_only")
    _print_review_result(state)
    _save_results(state)


def cmd_schedule() -> None:
    """启动定时任务（APScheduler）"""
    settings.validate()
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        print("请先安装 apscheduler：pip install apscheduler")
        sys.exit(1)

    from graph.workflow import run_workflow

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    def job_morning():
        logger.info("[定时任务] 09:15 触发+精筛 启动")
        state = run_workflow(run_mode="full")
        _print_trigger_result(state)
        _print_screener_result(state)
        _save_results(state)

    def job_review():
        logger.info("[定时任务] 15:35 复盘 启动")
        state = run_workflow(run_mode="review_only")
        _print_review_result(state)
        _save_results(state)

    scheduler.add_job(job_morning, "cron", hour=9, minute=15, id="morning_job",
                      name="触发+精筛（09:15）")
    scheduler.add_job(job_review, "cron", hour=15, minute=35, id="review_job",
                      name="每日复盘（15:35）")

    print("=" * 60)
    print("定时任务已注册：")
    print("  09:15 - 触发Agent + 精筛Agent")
    print("  15:35 - 复盘Agent")
    print("按 Ctrl+C 停止")
    print("=" * 60)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("定时任务已停止")


def main():
    parser = argparse.ArgumentParser(
        description="stock-agent-v2：三层Agent选股系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python main.py --trigger-only    仅运行触发检测（早晨手动）
  python main.py --event           触发 + 精筛（完整选股流程）
  python main.py --review          仅收盘复盘
  python main.py --schedule        启动定时任务（09:15 + 15:35）
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--trigger-only", action="store_true", help="仅运行触发检测")
    group.add_argument("--event", action="store_true", help="触发 + 精筛")
    group.add_argument("--review", action="store_true", help="仅收盘复盘")
    group.add_argument("--schedule", action="store_true", help="启动APScheduler定时任务")

    args = parser.parse_args()

    if args.trigger_only:
        cmd_trigger_only()
    elif args.event:
        cmd_event()
    elif args.review:
        cmd_review()
    elif args.schedule:
        cmd_schedule()


if __name__ == "__main__":
    main()
