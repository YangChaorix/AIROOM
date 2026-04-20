"""Stock Agent v6 entry point.

Usage:
    # 模式 A：从 triggers 事件队列消费（Phase 6 推荐）
    python main.py                       # 消费最早 1 个 pending trigger
    python main.py --consume 3           # 消费最多 3 个
    python main.py --consume all         # 消费所有 pending

    # 模式 B：合成 live trigger 后立即跑（不入队列，直接跑完标完成）
    python main.py --live                # 实时新闻 LLM 摘要（旧 trigger_fetcher，已退居其次）

    # 模式 C：fixture（测试用）
    python main.py default               # data/triggers_fixtures.json 的 "default"
    python main.py strong_policy
    python main.py weak_noise

    # 模式 D：个股分析（合成 trigger，直接跑）
    python main.py --stock 300750
    python main.py --stock 宁德时代
    python main.py --stock 300750 --no-peers
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from graph.builder import build_graph
from schemas.state import AgentState

_ROOT = Path(__file__).parent
DEFAULT_USER_ID = "dad_001"


def _load_fixture_trigger(trigger_key: str) -> dict:
    path = _ROOT / "data" / "triggers_fixtures.json"
    if not path.exists():
        legacy = _ROOT / "data" / "triggers_mock.json"
        if legacy.exists():
            path = legacy
    triggers = json.loads(path.read_text(encoding="utf-8"))
    if trigger_key not in triggers:
        raise KeyError(f"trigger key '{trigger_key}' not in {list(triggers.keys())}")
    return triggers[trigger_key]


def _load_live_trigger() -> dict:
    from tools.trigger_fetcher import get_live_trigger
    return get_live_trigger()


def _load_profile(user_id: str = DEFAULT_USER_ID) -> dict:
    try:
        from db.engine import get_session
        from db.repos.users_repo import load_profile as db_load_profile
        with get_session() as sess:
            try:
                return db_load_profile(sess, user_id)
            except ValueError:
                raise RuntimeError(
                    f"user_id={user_id} 不在 DB 中。请先运行:\n"
                    f"  python scripts/seed_from_json.py --user-id {user_id}"
                )
    except ImportError:
        return json.loads((_ROOT / "config" / "user_profile.json").read_text(encoding="utf-8"))


def _run_with_trigger(trigger: dict, trigger_key: str, mode: str,
                      user_id: str, consumed_trigger_db_id: int = None) -> AgentState:
    """跑一次 Supervisor 流程，trigger 已准备好。

    consumed_trigger_db_id：如果是从 triggers 队列消费模式，传入该 trigger 的 db id，
    跑完后调 triggers_queue_repo.mark_completed(id, run_id)。
    """
    load_dotenv(_ROOT / ".env")

    run_id = None
    try:
        from db.engine import get_session
        from db.repos.runs_repo import create_run
        from db.repos.triggers_repo import insert_trigger
        with get_session() as sess:
            run_id = create_run(sess, user_id=user_id, trigger_key=trigger_key)
        # 如果是"消费队列"模式，trigger 已在 DB（db_id 非空），不再 insert
        if consumed_trigger_db_id is None:
            with get_session() as sess:
                insert_trigger(sess, run_id=run_id, trigger=trigger, mode=mode)
    except Exception as e:
        print(f"[main] DB run init failed: {e}", file=sys.stderr)

    initial: AgentState = {
        "trigger_summary": trigger,
        "user_profile": _load_profile(user_id),
        "completed_steps": [],
        "round": 0,
        "run_started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "run_id": run_id,
    }

    graph = build_graph()
    try:
        final_state = graph.invoke(initial, config={"recursion_limit": 30})
        if run_id is not None:
            try:
                from db.engine import get_session
                from db.repos.runs_repo import mark_finished
                with get_session() as sess:
                    mark_finished(sess, run_id)
                # 如果是消费模式，更新 triggers 行
                if consumed_trigger_db_id is not None:
                    from db.repos.triggers_queue_repo import mark_completed
                    with get_session() as sess:
                        mark_completed(sess, consumed_trigger_db_id, run_id)
            except Exception as e:
                print(f"[main] mark_finished failed: {e}", file=sys.stderr)
        return final_state
    except Exception as e:
        if run_id is not None:
            try:
                from db.engine import get_session
                from db.repos.runs_repo import mark_failed
                with get_session() as sess:
                    mark_failed(sess, run_id, str(e))
                if consumed_trigger_db_id is not None:
                    from db.repos.triggers_queue_repo import mark_failed as tq_failed
                    with get_session() as sess:
                        tq_failed(sess, consumed_trigger_db_id, str(e))
            except Exception:
                pass
        raise


def run(trigger_key: str = "live", user_id: str = DEFAULT_USER_ID,
        stock: str = None, with_peers: bool = True) -> AgentState:
    """原版 API：指定模式跑一次。保留用于兼容老测试。"""
    load_dotenv(_ROOT / ".env")

    if stock:
        from tools.single_stock_trigger import build_single_stock_trigger
        trigger = build_single_stock_trigger(stock, with_peers=with_peers)
        return _run_with_trigger(trigger, f"stock:{stock}", "individual_stock", user_id)
    elif trigger_key == "live":
        trigger = _load_live_trigger()
        return _run_with_trigger(trigger, "live", "live", user_id)
    else:
        trigger = _load_fixture_trigger(trigger_key)
        return _run_with_trigger(trigger, trigger_key, "fixture", user_id)


def consume_queue(n: int, user_id: str = DEFAULT_USER_ID) -> dict:
    """从 triggers 队列消费 pending，最多 n 个（n='all' 表示全部）。

    返回统计 dict。
    """
    load_dotenv(_ROOT / ".env")
    from db.engine import get_session
    from db.repos.triggers_queue_repo import claim_next_pending

    processed = 0
    errors = 0
    limit = None if n == "all" else int(n)
    while True:
        if limit is not None and processed >= limit:
            break
        with get_session() as sess:
            trigger = claim_next_pending(sess)
        if trigger is None:
            print(f"[consume] 队列已空，已消费 {processed} 个")
            break

        trigger_db_id = trigger.pop("db_id")
        trigger_key = f"queue:{trigger['trigger_id']}"
        print(f"[consume] 处理 trigger id={trigger_db_id} priority={trigger.get('priority')} "
              f"headline={trigger.get('headline', '')[:60]}")
        try:
            state = _run_with_trigger(trigger, trigger_key, trigger.get("mode", "agent_generated"),
                                      user_id, consumed_trigger_db_id=trigger_db_id)
            rid = state.get("run_id")
            print(f"  → Done run_id={rid}. View: python scripts/show_run.py {rid}")
            processed += 1
        except Exception as e:
            print(f"  → 失败: {e}", file=sys.stderr)
            errors += 1
    return {"processed": processed, "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock Agent v6")
    parser.add_argument("trigger_key", nargs="?", default=None,
                        help="live / default / strong_policy / weak_noise（不传默认消费队列）")
    parser.add_argument("--stock", default=None,
                        help="股票代码（6 位）或公司名：启用个股分析模式")
    parser.add_argument("--no-peers", action="store_true",
                        help="单股模式下不拉对标股，只分析主股")
    parser.add_argument("--live", action="store_true",
                        help="绕过队列，实时合成 trigger 跑一次")
    parser.add_argument("--consume", default=None,
                        help="从 triggers 队列消费：1 / 3 / all；不传默认消费 1 个")
    args = parser.parse_args()

    # 优先判断特殊模式
    if args.stock:
        state = run(stock=args.stock, with_peers=not args.no_peers)
        rid = state.get("run_id")
        print(f"Done. run_id={rid}. View: python scripts/show_run.py {rid}")
    elif args.live or args.trigger_key == "live":
        state = run(trigger_key="live")
        rid = state.get("run_id")
        print(f"Done. run_id={rid}. View: python scripts/show_run.py {rid}")
    elif args.trigger_key:
        # fixture 模式
        state = run(trigger_key=args.trigger_key)
        rid = state.get("run_id")
        print(f"Done. run_id={rid}. View: python scripts/show_run.py {rid}")
    else:
        # 默认：消费队列
        n = args.consume or "1"
        stats = consume_queue(n=n)
        print(f"Consumed: {stats}")
