"""
stock-agent-v3 主入口（v1.3）

使用方式：
  python main.py --init-db         # 初始化数据库（首次运行）
  python main.py --trigger-only    # 仅运行触发检测
  python main.py --event           # 触发 + 精筛（无复盘）
  python main.py --review          # 仅收盘复盘
  python main.py --collect         # 执行一次新闻采集（写入缓存）
  python main.py --schedule        # 启动定时任务（09:15触发+精筛，15:35复盘，后台采集）

v1.1 新增：
  - Serper Web 搜索政策新闻
  - 财联社电报采集
  - 事件新鲜度追踪（跨日去重）
  - 期货品种扩展（铜/铝/锌/铅/镍/铁矿石/白银等）
  - review_agent market data retry/fallback

v1.2 新增：
  - 动态新闻采集与缓存（--collect 命令）
  - 按时效性分级采集（HIGH/MEDIUM/LOW）
  - trigger_agent 优先读取当日缓存

v1.3 新增：
  - SQLite 存储层（--init-db 初始化，自动建表）
  - 触发/精筛/复盘结果写入 DB
  - 新闻缓存和事件历史迁移至 DB
  - Prompt 版本管理（DB 存储，代码字符串作为 fallback）
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
    初始化日志，支持两个环境变量开关：
      LOG_FILE_ENABLED=true/false  是否写文件日志（默认 true）
      LOG_LEVEL=DEBUG/INFO/WARNING 控制台日志级别（默认 INFO）
    文件固定写入 logs/YYYY-MM-DD.log，级别 DEBUG。
    """
    from dotenv import load_dotenv
    load_dotenv()

    log_file_enabled = os.getenv("LOG_FILE_ENABLED", "true").lower() != "false"
    console_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    console_level = getattr(logging, console_level_name, logging.INFO)

    today = datetime.now().strftime("%Y-%m-%d")
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{today}.log")

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    # 控制台 handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(ch)

    # 文件 handler（可关闭）
    if log_file_enabled:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(fmt, datefmt))
        root.addHandler(fh)

    # 抑制第三方库的 DEBUG 噪音
    for noisy in ["httpx", "httpcore", "urllib3", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    status = f"文件日志: {'开启 → ' + os.path.abspath(log_file) if log_file_enabled else '关闭'} | 控制台级别: {console_level_name}"
    logging.getLogger(__name__).info(status)
    return log_file


setup_logging()
logger = logging.getLogger(__name__)

# 自动检测并初始化 DB（幂等，已存在不影响）
try:
    from tools.db import db
    db.init_db()
    logger.debug(f"DB 就绪: {db.db_path}")
except Exception as _db_init_err:
    logger.warning(f"DB 自动初始化失败（不影响主流程）: {_db_init_err}")


def _log(msg: str) -> None:
    """同时输出到终端和日志文件"""
    print(msg)
    logger.info(msg)


def _print_trigger_result(state: dict) -> None:
    tr = state.get("trigger_result") or {}
    _log("\n" + "=" * 60)
    _log("【触发Agent 输出】")
    _log(f"日期：{tr.get('date', 'N/A')}")
    _log(f"是否触发：{tr.get('has_triggers', False)}")
    triggers = tr.get("triggers", [])
    _log(f"触发条目数：{len(triggers)}")
    for i, t in enumerate(triggers, 1):
        _log(f"\n  [{i}] {t.get('type', '')} | 强度：{t.get('strength', '')} | 新鲜度：{t.get('freshness', 'N/A')}")
        _log(f"      摘要：{t.get('summary', '')[:100]}...")
        _log(f"      行业：{', '.join(t.get('industries', []))}")
        if t.get("freshness_reason"):
            _log(f"      新鲜度理由：{t.get('freshness_reason', '')[:80]}")
        companies = t.get("companies", {})
        for cat, lst in companies.items():
            if lst:
                _log(
                    f"      {cat}：{', '.join(lst[:3]) if isinstance(lst[0], str) else str(lst[:3])}"
                )
    if tr.get("error"):
        _log(f"错误：{tr['error']}")
    _log("=" * 60)


def _print_screener_result(state: dict) -> None:
    sr = state.get("screener_result") or {}
    if sr.get("skipped"):
        _log("\n【精筛Agent】跳过（无触发信息）")
        return
    _log("\n" + "=" * 60)
    _log("【精筛Agent 输出 - Top 20】")
    top20 = sr.get("top20", [])
    for stock in top20:
        scores = stock.get("scores", {})
        total = stock.get("total_score", sum(v.get("score", 0) for v in scores.values()))
        _log(
            f"\n  #{stock.get('rank', '?')} {stock.get('name', '')} ({stock.get('code', '')})"
            f" | 总分：{total}/18"
        )
        _log(f"      触发：{stock.get('trigger_reason', '')[:60]}")
        for dim, info in scores.items():
            _log(f"      {dim}: {info.get('score', '?')}分 - {info.get('reason', '')[:40]}")
        _log(f"      推荐：{stock.get('recommendation', '')[:120]}")
        _log(f"      风险：{stock.get('risk', '')[:60]}")
    if sr.get("error"):
        _log(f"错误：{sr['error']}")
    _log("=" * 60)


def _print_review_result(state: dict) -> None:
    rr = state.get("review_result") or {}
    _log("\n" + "=" * 60)
    _log("【复盘Agent 输出】")
    if rr.get("market_data_fallback"):
        _log("⚠️ 注意：市场行情数据使用了 fallback（获取失败）")
    if rr.get("error"):
        _log(f"错误：{rr['error']}")
    else:
        _log(rr.get("review_markdown", "（无内容）"))
    _log("=" * 60)



def cmd_init_db() -> None:
    """初始化数据库，写入初始 Prompt 版本"""
    from tools.db import db
    from agents.trigger_agent import TRIGGER_SYSTEM_PROMPT
    from agents.screener_agent import SCREENER_SYSTEM_PROMPT
    from agents.review_agent import REVIEW_SYSTEM_PROMPT

    logger.info("初始化数据库...")
    db.init_db()

    # 迁移已有 events.json（如存在）
    _migrate_events_json(db)

    # 写入初始 Prompt（仅当该 agent 尚无任何版本时才写）
    _init_prompt_if_empty(db, "trigger", "system_prompt", TRIGGER_SYSTEM_PROMPT, "v1.1")
    _init_prompt_if_empty(db, "screener", "system_prompt", SCREENER_SYSTEM_PROMPT, "v1.1")
    _init_prompt_if_empty(db, "review", "system_prompt", REVIEW_SYSTEM_PROMPT, "v1.1")

    print(f"\n【数据库初始化完成】")
    print(f"DB 路径: {db.db_path}")
    import os
    size_kb = os.path.getsize(db.db_path) / 1024
    print(f"DB 大小: {size_kb:.1f} KB")
    for agent in ("trigger", "screener", "review"):
        versions = db.list_prompt_versions(agent)
        print(f"  {agent} prompts: {len(versions)} 个版本")


def _migrate_events_json(db) -> None:
    """将已有的 events.json 迁移到 DB（如存在且 DB 中无数据）"""
    import json, os
    from config.settings import settings
    events_file = os.path.join(settings.agent.event_history_dir, "events.json")
    if not os.path.exists(events_file):
        return
    try:
        with db.get_conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM event_history").fetchone()[0]
        if count > 0:
            logger.info(f"DB event_history 已有 {count} 条，跳过 events.json 迁移")
            return
        with open(events_file, "r", encoding="utf-8") as f:
            history = json.load(f)
        if not isinstance(history, dict):
            return
        with db.get_conn() as conn:
            for event_hash, record in history.items():
                conn.execute(
                    """INSERT OR IGNORE INTO event_history
                       (event_hash, first_seen, last_seen, summary, event_type)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        event_hash,
                        record.get("first_seen", ""),
                        record.get("last_seen", ""),
                        record.get("summary", ""),
                        record.get("type", ""),
                    ),
                )
        logger.info(f"events.json 已迁移到 DB：{len(history)} 条事件")
        print(f"  迁移 events.json → DB event_history：{len(history)} 条")
    except Exception as e:
        logger.warning(f"events.json 迁移失败（不影响主流程）: {e}")


def _init_prompt_if_empty(db, agent_name: str, prompt_name: str,
                           content: str, version: str) -> None:
    """仅当该 agent/prompt_name 尚无任何版本时，写入初始版本"""
    existing = db.list_prompt_versions(agent_name)
    if any(p["prompt_name"] == prompt_name for p in existing):
        logger.debug(f"Prompt {agent_name}/{prompt_name} 已存在，跳过初始写入")
        return
    db.save_prompt(agent_name, prompt_name, content, version, note="初始版本（auto from --init-db）")
    logger.info(f"Prompt 已写入 DB：{agent_name}/{prompt_name} {version}")


def cmd_trigger_only() -> None:
    """仅运行触发检测"""
    settings.validate()
    from graph.workflow import run_workflow

    logger.info("启动模式：仅触发检测")
    state = run_workflow(run_mode="trigger_only")
    _print_trigger_result(state)


def cmd_event() -> None:
    """触发 + 精筛"""
    settings.validate()
    from graph.workflow import run_workflow

    logger.info("启动模式：触发 + 精筛")
    state = run_workflow(run_mode="full")
    _print_trigger_result(state)
    _print_screener_result(state)


def cmd_review() -> None:
    """仅收盘复盘"""
    settings.validate()
    from graph.workflow import run_workflow

    logger.info("启动模式：仅复盘")
    state = run_workflow(run_mode="review_only")
    _print_review_result(state)


def cmd_collect() -> None:
    """执行一次新闻采集，写入缓存"""
    from tools.news_collector import collect_all_due_sources, NewsCacheManager
    logger.info("启动模式：新闻采集")
    result = collect_all_due_sources()
    mgr = NewsCacheManager()
    cache = mgr.load_today()
    total = len(cache.get("news", []))
    logger.info(f"采集完成：{result}，当日缓存总计 {total} 条")
    print(f"\n【新闻采集完成】")
    print(f"本次各来源新增：{result}")
    print(f"当日缓存总计：{total} 条")


def cmd_schedule() -> None:
    """启动定时任务（APScheduler）"""
    settings.validate()
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        print("请先安装 apscheduler：pip install apscheduler")
        sys.exit(1)

    from graph.workflow import run_workflow
    from tools.db import db as _sched_db

    # 从 DB 读取调度配置（支持运行时修改后重启生效）
    def _int(key, default): return int(_sched_db.get_config(key, default) or default)
    def _days(key, default):
        raw = (_sched_db.get_config(key, default) or default).strip()
        return raw if raw else None  # None = 每天

    trigger_hour   = _int("schedule_trigger_hour",   9)
    trigger_minute = _int("schedule_trigger_minute", 15)
    trigger_days   = _days("schedule_trigger_days",  "1,2,3,4,5")
    review_hour    = _int("schedule_review_hour",    15)
    review_minute  = _int("schedule_review_minute",  35)
    review_days    = _days("schedule_review_days",   "1,2,3,4,5")

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    def job_morning():
        logger.info(f"[定时任务] {trigger_hour:02d}:{trigger_minute:02d} 触发+精筛 启动")
        state = run_workflow(run_mode="full")
        _print_trigger_result(state)
        _print_screener_result(state)

    def job_review():
        logger.info(f"[定时任务] {review_hour:02d}:{review_minute:02d} 复盘 启动")
        state = run_workflow(run_mode="review_only")
        _print_review_result(state)

    scheduler.add_job(
        job_morning, "cron",
        hour=trigger_hour, minute=trigger_minute,
        day_of_week=trigger_days,
        id="morning_job", name=f"触发+精筛（{trigger_hour:02d}:{trigger_minute:02d} 周{trigger_days or '每天'}）"
    )
    scheduler.add_job(
        job_review, "cron",
        hour=review_hour, minute=review_minute,
        day_of_week=review_days,
        id="review_job", name=f"每日复盘（{review_hour:02d}:{review_minute:02d} 周{review_days or '每天'}）"
    )

    # 新闻采集：单一 job，时段/间隔过滤由 is_source_due() 内部处理
    schedule_hours = settings.agent.collect_schedule_hours
    schedule_interval = settings.agent.collect_schedule_interval
    scheduler.add_job(
        cmd_collect, "cron",
        hour=schedule_hours,
        minute=f"*/{schedule_interval}",
        id="collect_job",
        name=f"新闻采集（{schedule_hours}点，每{schedule_interval}分钟触发，内部按优先级时段过滤）",
    )

    print("=" * 60)
    print("定时任务已注册（stock-agent-v3）：")
    print(f"  {schedule_hours}点 每{schedule_interval}分钟 - 新闻采集（各优先级独立时段过滤）")
    print(f"    HIGH  活跃时段: {settings.agent.collect_high_hours}  "
          f"间隔: {settings.agent.collect_interval_high}m")
    print(f"    MEDIUM活跃时段: {settings.agent.collect_medium_hours}  "
          f"间隔: {settings.agent.collect_interval_medium}m")
    print(f"    LOW   活跃时段: {settings.agent.collect_low_hours}  "
          f"间隔: {settings.agent.collect_interval_low}m")
    print(f"  {trigger_hour:02d}:{trigger_minute:02d} (周{trigger_days or '每天'}) - 触发Agent + 精筛Agent")
    print(f"  {review_hour:02d}:{review_minute:02d} (周{review_days or '每天'}) - 复盘Agent")
    print("按 Ctrl+C 停止")
    print("=" * 60)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("定时任务已停止")


def main():
    parser = argparse.ArgumentParser(
        description="stock-agent-v3（v1.3）：三层Agent选股系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python main.py --init-db         初始化数据库（首次使用）
  python main.py --trigger-only    仅运行触发检测（早晨手动）
  python main.py --event           触发 + 精筛（完整选股流程）
  python main.py --review          仅收盘复盘
  python main.py --schedule        启动定时任务（09:15 + 15:35）

v1.3 新增：SQLite 存储层 | Prompt 版本管理 | --init-db 初始化命令
        """,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init-db", action="store_true", help="初始化数据库并写入初始 Prompt")
    group.add_argument("--trigger-only", action="store_true", help="仅运行触发检测")
    group.add_argument("--event", action="store_true", help="触发 + 精筛")
    group.add_argument("--review", action="store_true", help="仅收盘复盘")
    group.add_argument("--collect", action="store_true", help="执行一次新闻采集")
    group.add_argument("--schedule", action="store_true", help="启动APScheduler定时任务")

    args = parser.parse_args()

    if args.init_db:
        cmd_init_db()
    elif args.trigger_only:
        cmd_trigger_only()
    elif args.event:
        cmd_event()
    elif args.review:
        cmd_review()
    elif args.collect:
        cmd_collect()
    elif args.schedule:
        cmd_schedule()


if __name__ == "__main__":
    main()
