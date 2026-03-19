"""
LangGraph 三层工作流（v1.1）
START → trigger_node → [has_triggers?]
                              ↓ Yes
                       screener_node
                              ↓
                       review_node → END
                              ↓ No
                       review_node → END

run_mode: 'full' | 'trigger_only' | 'review_only'
v1.1: WorkflowState 新增 search_results 字段用于传递 Web 搜索结果
"""

import json
import logging
import os
from datetime import datetime
from typing import TypedDict, Optional, Literal

from langgraph.graph import StateGraph, START, END

from agents.trigger_agent import run_trigger_agent
from agents.screener_agent import run_screener_agent
from agents.review_agent import run_review_agent
from config.settings import settings

logger = logging.getLogger(__name__)


class WorkflowState(TypedDict):
    run_mode: str               # 'full' | 'trigger_only' | 'review_only'
    date: str
    trigger_result: Optional[dict]
    screener_result: Optional[dict]
    review_result: Optional[dict]
    search_results: Optional[list]   # v1.1: Serper Web 搜索结果（可选透传）
    error: Optional[str]


def _save_daily_push(trigger_result: dict, screener_result: dict) -> str:
    """将当日推送记录写入 data/daily_push/YYYY-MM-DD.json"""
    data_dir = settings.agent.data_dir
    os.makedirs(data_dir, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(data_dir, f"{today}.json")
    payload = {
        "date": today,
        "trigger_result": trigger_result,
        "screener_result": screener_result,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(f"当日推送记录已保存: {file_path}")
    return file_path


def _load_daily_push(date: str = None) -> Optional[dict]:
    """读取 data/daily_push/YYYY-MM-DD.json"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(settings.agent.data_dir, f"{date}.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


# ── 节点函数 ───────────────────────────────────────────────

def trigger_node(state: WorkflowState) -> WorkflowState:
    """触发Agent节点"""
    if state["run_mode"] == "review_only":
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
        # 保存推送记录
        _save_daily_push(trigger_result, result)
        return {**state, "screener_result": result}
    except Exception as e:
        logger.error(f"screener_node 异常: {e}")
        return {**state, "screener_result": {"error": str(e)}, "error": str(e)}


def review_node(state: WorkflowState) -> WorkflowState:
    """复盘Agent节点"""
    if state["run_mode"] == "trigger_only":
        return {**state, "review_result": None}
    try:
        # 尝试读取当日推送记录（可能由 screener_node 写入，也可能是历史记录）
        daily_push = _load_daily_push()
        if daily_push is None and state.get("trigger_result") and state.get("screener_result"):
            daily_push = {
                "trigger_result": state["trigger_result"],
                "screener_result": state["screener_result"],
            }
        result = run_review_agent(daily_push=daily_push)
        return {**state, "review_result": result}
    except Exception as e:
        logger.error(f"review_node 异常: {e}")
        return {**state, "review_result": {"error": str(e)}, "error": str(e)}


def route_after_trigger(state: WorkflowState) -> Literal["screener_node", "review_node"]:
    """
    触发后路由：
    - trigger_only 模式 → 直接到 review_node（但 review_node 会跳过）
    - 有触发 → screener_node
    - 无触发 → review_node（仅复盘）
    """
    run_mode = state.get("run_mode", "full")
    if run_mode == "trigger_only":
        return "review_node"

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
        run_id = db.start_run(run_mode)
        logger.debug(f"DB run_logs 记录开始：run_id={run_id}, mode={run_mode}")
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
