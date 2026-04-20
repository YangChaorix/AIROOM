"""APScheduler 守护进程入口。

用法：
    python scheduler/run.py            # 按 config/news_channels.json 注册所有任务，前台运行
    python scheduler/run.py --once all # 立即触发所有渠道各一次，不进入调度循环
    python scheduler/run.py --once news_cctv  # 立即只跑指定渠道一次

停止：Ctrl+C（或 kill）。
"""
import argparse
import json
import logging
import signal
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

from db.repos.system_logs_repo import log  # noqa: E402
from scheduler.tasks import AGENT_TASKS, fetch_channel  # noqa: E402

_CONFIG_PATH = _ROOT / "config" / "news_channels.json"
_AGENT_CONFIG_PATH = _ROOT / "config" / "agent_schedule.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scheduler")


def _load_channels():
    cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    channels = cfg.get("channels", [])
    return [c for c in channels if c.get("enabled", True)], cfg.get("_timezone", "Asia/Shanghai")


def _load_agents():
    if not _AGENT_CONFIG_PATH.exists():
        return []
    cfg = json.loads(_AGENT_CONFIG_PATH.read_text(encoding="utf-8"))
    agents = cfg.get("agents", [])
    return [a for a in agents if a.get("enabled", True)]


def _run_once(target: str) -> None:
    """立即执行一次（用于 --once 模式）。支持渠道名 / agent 名 / 'all' / 'agents'。"""
    channels, _ = _load_channels()
    agents = _load_agents()

    if target == "all":
        for ch in channels:
            logger.info(f"→ 立即执行渠道 {ch['name']}")
            logger.info(f"← {ch['name']} 结果: {fetch_channel(ch)}")
        for a in agents:
            logger.info(f"→ 立即执行 Agent {a['name']}")
            fn = AGENT_TASKS.get(a["task"])
            if fn is None:
                logger.error(f"未实现的 agent task: {a['task']}")
                continue
            logger.info(f"← {a['name']} 结果: {fn(**a.get('kwargs', {}))}")
        return

    if target == "channels":
        for ch in channels:
            logger.info(f"→ 立即执行渠道 {ch['name']}")
            logger.info(f"← {ch['name']} 结果: {fetch_channel(ch)}")
        return

    if target == "agents":
        for a in agents:
            logger.info(f"→ 立即执行 Agent {a['name']}")
            fn = AGENT_TASKS.get(a["task"])
            logger.info(f"← {a['name']} 结果: {fn(**a.get('kwargs', {}))}")
        return

    # 查渠道
    ch = next((c for c in channels if c["name"] == target), None)
    if ch:
        logger.info(f"→ 立即执行渠道 {target}")
        logger.info(f"← {target} 结果: {fetch_channel(ch)}")
        return

    # 查 agent
    a = next((x for x in agents if x["name"] == target), None)
    if a:
        logger.info(f"→ 立即执行 Agent {target}")
        fn = AGENT_TASKS.get(a["task"])
        logger.info(f"← {target} 结果: {fn(**a.get('kwargs', {}))}")
        return

    logger.error(f"找不到 {target}（既不是渠道也不是 agent）")


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", default=None,
                        help="立即触发一次，值=渠道名或 'all'；不进入调度循环")
    args = parser.parse_args()

    if args.once:
        _run_once(args.once)
        return

    channels, tz = _load_channels()
    agents = _load_agents()
    if not channels and not agents:
        logger.error("无启用的渠道或 agent。")
        sys.exit(1)

    scheduler = BlockingScheduler(timezone=tz)

    for ch in channels:
        cron_cfg = ch.get("cron", {})
        trigger = CronTrigger(**cron_cfg, timezone=tz)
        scheduler.add_job(
            func=fetch_channel,
            trigger=trigger,
            args=[ch],
            id=f"news_{ch['name']}",
            name=ch["name"],
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info(f"已注册渠道：{ch['name']}  cron={cron_cfg}")

    for a in agents:
        cron_cfg = a.get("cron", {})
        trigger = CronTrigger(**cron_cfg, timezone=tz)
        fn = AGENT_TASKS.get(a["task"])
        if fn is None:
            logger.error(f"跳过 agent {a['name']}：未实现的 task={a['task']}")
            continue
        scheduler.add_job(
            func=fn,
            trigger=trigger,
            kwargs=a.get("kwargs", {}),
            id=f"agent_{a['name']}",
            name=a["name"],
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info(f"已注册 Agent：{a['name']}  cron={cron_cfg}  kwargs={a.get('kwargs', {})}")

    log("info", "scheduler.boot",
        f"启动调度器，注册 {len(channels)} 个渠道 + {len(agents)} 个 agent",
        context={"channels": [c["name"] for c in channels],
                 "agents": [a["name"] for a in agents], "timezone": tz})

    def _shutdown(signum, frame):
        logger.info(f"收到信号 {signum}，停止调度器")
        scheduler.shutdown(wait=False)
        log("info", "scheduler.shutdown", f"调度器退出（信号 {signum}）")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("调度器启动中...  Ctrl+C 退出")
    scheduler.start()


if __name__ == "__main__":
    _main()
