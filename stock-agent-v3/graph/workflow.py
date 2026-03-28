"""
LangGraph 三层工作流（v1.2）
START → trigger_node → [has_triggers?]
                              ↓ Yes
                       screener_node
                              ↓
                       review_node → END
                              ↓ No
                       review_node → END

run_mode: 'picks_only' | 'review_only' | 'critic_only'
v1.1: WorkflowState 新增 search_results 字段用于传递 Web 搜索结果
v1.2: WorkflowState 新增 critic_result 字段；新增 run_critic_workflow() 独立函数
"""

import logging
from datetime import datetime
from typing import TypedDict, Optional, Literal

from langgraph.graph import StateGraph, START, END

from agents.trigger_agent import run_trigger_agent
from agents.screener_agent import run_screener_agent
from agents.review_agent import run_review_agent

logger = logging.getLogger(__name__)


class WorkflowState(TypedDict):
    run_mode: str               # 'full' | 'trigger_only' | 'review_only' | 'critic_only'
    date: str
    trigger_result: Optional[dict]
    screener_result: Optional[dict]
    review_result: Optional[dict]
    search_results: Optional[list]   # v1.1: Serper Web 搜索结果（可选透传）
    critic_result: Optional[dict]    # v1.2: 批评Agent结果
    error: Optional[str]


def _load_daily_push_from_db(date: str = None) -> Optional[dict]:
    """从 DB 读取当日触发+精筛结果，拼装为 daily_push 格式"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    try:
        from tools.db import db
        triggers = db.get_triggers(date)
        screener_rows = db.get_screener(date)
        if not triggers and not screener_rows:
            return None
        top20 = [
            {
                "rank": r["rank"],
                "name": r["stock_name"],
                "code": r["stock_code"],
                "trigger_reason": r.get("trigger_reason", ""),
                "total_score": r.get("total_score"),
                "recommendation": r.get("recommendation", ""),
                "risk": r.get("risk", ""),
            }
            for r in screener_rows
        ]
        return {
            "trigger_result": {"has_triggers": len(triggers) > 0, "triggers": triggers},
            "screener_result": {"top20": top20},
        }
    except Exception as e:
        logger.warning(f"从 DB 加载 daily_push 失败: {e}")
        return None


# ── 节点函数 ───────────────────────────────────────────────

def trigger_node(state: WorkflowState) -> WorkflowState:
    """触发Agent节点"""
    if state["run_mode"].split(":")[0] == "review_only":
        return {**state, "trigger_result": None}
    try:
        result = run_trigger_agent()
        return {**state, "trigger_result": result}
    except Exception as e:
        logger.error(f"trigger_node 异常: {e}")
        return {
            **state,
            "trigger_result": {"has_triggers": False, "error": str(e)},
            "error": str(e),
        }


def screener_node(state: WorkflowState) -> WorkflowState:
    """精筛Agent节点"""
    trigger_result = state.get("trigger_result") or {}
    try:
        result = run_screener_agent(trigger_result)
        return {**state, "screener_result": result}
    except Exception as e:
        logger.error(f"screener_node 异常: {e}")
        return {**state, "screener_result": {"error": str(e)}, "error": str(e)}


def review_node(state: WorkflowState) -> WorkflowState:
    """复盘Agent节点"""
    # picks_only 模式跳过复盘
    if state["run_mode"].split(":")[0] == "picks_only":
        return {**state, "review_result": None}
    try:
        # 优先从当前 state 取，否则从 DB 加载当日数据
        if state.get("trigger_result") and state.get("screener_result"):
            daily_push = {
                "trigger_result": state["trigger_result"],
                "screener_result": state["screener_result"],
            }
        else:
            daily_push = _load_daily_push_from_db()
        result = run_review_agent(daily_push=daily_push)
        return {**state, "review_result": result}
    except Exception as e:
        logger.error(f"review_node 异常: {e}")
        return {**state, "review_result": {"error": str(e)}, "error": str(e)}


def route_after_trigger(state: WorkflowState) -> Literal["screener_node", "review_node"]:
    """
    触发后路由：
    - 有触发 → screener_node
    - 无触发 → review_node（仅复盘）
    """
    trigger_result = state.get("trigger_result") or {}
    if trigger_result.get("has_triggers"):
        return "screener_node"
    else:
        return "review_node"


def route_after_screener(state: WorkflowState) -> Literal["review_node"]:
    return "review_node"


# ── 构建图 ────────────────────────────────────────────────

def create_workflow() -> StateGraph:
    graph = StateGraph(WorkflowState)

    graph.add_node("trigger_node", trigger_node)
    graph.add_node("screener_node", screener_node)
    graph.add_node("review_node", review_node)

    graph.add_edge(START, "trigger_node")
    graph.add_conditional_edges(
        "trigger_node",
        route_after_trigger,
        {"screener_node": "screener_node", "review_node": "review_node"},
    )
    graph.add_edge("screener_node", "review_node")
    graph.add_edge("review_node", END)

    return graph.compile()


def run_workflow(run_mode: str = "full") -> WorkflowState:
    """
    运行工作流

    Args:
        run_mode: 'full' | 'trigger_only' | 'review_only'

    Returns:
        最终状态
    """
    # 记录运行开始（v1.2 新增）
    run_id = None
    try:
        from tools.db import db
        from config.settings import _load_models_json
        _mcfg = _load_models_json()
        _models = {a: v["model"] for a, v in _mcfg.get("agents", {}).items()}
        run_id = db.start_run(run_mode, models=_models)
        logger.debug(f"DB run_logs 记录开始：run_id={run_id}, mode={run_mode}, models={_models}")
    except Exception as e:
        logger.warning(f"DB start_run 失败（不影响主流程）: {e}")

    try:
        workflow = create_workflow()
        initial_state: WorkflowState = {
            "run_mode": run_mode,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "trigger_result": None,
            "screener_result": None,
            "review_result": None,
            "search_results": None,
            "critic_result": None,
            "error": None,
        }
        final_state = workflow.invoke(initial_state)

        if run_id is not None:
            try:
                from tools.db import db
                db.finish_run(run_id, "success")
            except Exception as e:
                logger.warning(f"DB finish_run 失败: {e}")

        return final_state

    except Exception as e:
        if run_id is not None:
            try:
                from tools.db import db
                db.finish_run(run_id, "error", str(e))
            except Exception:
                pass
        raise


def run_critic_workflow(run_date: str = None, trigger_mode: str = "manual") -> WorkflowState:
    """
    独立运行批评 Agent，不依赖 trigger/screener/review 节点。
    记录 run_log（run_mode='critic_only:manual' 或 'critic_only:auto'）。

    Args:
        run_date: 要分析的日期（默认今日）
        trigger_mode: 'manual' | 'auto'

    Returns:
        WorkflowState-compatible dict
    """
    from agents.critic_agent import run_critic_agent
    today = run_date or datetime.now().strftime("%Y-%m-%d")
    run_mode = f"critic_only:{trigger_mode}"

    run_id = None
    try:
        from tools.db import db
        run_id = db.start_run(run_mode)
        logger.debug(f"批评Agent run_log 开始：run_id={run_id}, date={today}")
    except Exception as e:
        logger.warning(f"DB start_run 失败: {e}")

    try:
        result = run_critic_agent(run_date=today)
        status = "error" if result.get("error") else "success"
        if run_id is not None:
            try:
                from tools.db import db
                db.finish_run(run_id, status)
            except Exception as e:
                logger.warning(f"DB finish_run 失败: {e}")

        return {
            "run_mode": run_mode,
            "date": today,
            "trigger_result": None,
            "screener_result": None,
            "review_result": None,
            "search_results": None,
            "critic_result": result,
            "error": result.get("error"),
        }
    except Exception as e:
        if run_id is not None:
            try:
                from tools.db import db
                db.finish_run(run_id, "error", str(e))
            except Exception:
                pass
        raise
