"""
事件驱动三层 LangGraph 工作流

拓扑：
  START → trigger_node → [条件边] → screener_node → review_node → END
                              ↓ (未触发)
                             END

run_mode:
  "full"         — 触发 + 精筛（早晨 09:15 使用）
  "trigger_only" — 仅触发检测
  "review_only"  — 仅收盘复盘
"""

import asyncio
from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.review_agent import run_review_agent
from agents.screener_agent import run_screener_agent
from agents.trigger_agent import run_trigger_agent


# ─── 状态定义 ────────────────────────────────────────────────────────────────

class EventDrivenState(TypedDict, total=False):
    run_mode: str                         # "full" | "trigger_only" | "review_only"
    trigger_result: Optional[dict]
    screener_result: Optional[dict]
    review_result: Optional[dict]
    date: str
    errors: list[str]
    is_complete: bool


# ─── 节点函数 ────────────────────────────────────────────────────────────────

async def trigger_node(state: EventDrivenState) -> EventDrivenState:
    """Agent 1：事件触发扫描"""
    try:
        result = await run_trigger_agent()
        return {**state, "trigger_result": result}
    except Exception as e:
        errors = list(state.get("errors", []))
        errors.append(f"trigger_node error: {str(e)}")
        return {
            **state,
            "trigger_result": {
                "triggered": False,
                "hit_conditions": [],
                "affected_industries": [],
                "affected_companies": [],
                "c4_price_data": [],
                "trigger_summary": f"Agent 1 执行异常: {str(e)}",
            },
            "errors": errors,
        }


async def screener_node(state: EventDrivenState) -> EventDrivenState:
    """Agent 2：企业精筛"""
    trigger_result = state.get("trigger_result", {})
    try:
        result = await run_screener_agent(trigger_result)
        return {**state, "screener_result": result}
    except Exception as e:
        errors = list(state.get("errors", []))
        errors.append(f"screener_node error: {str(e)}")
        return {
            **state,
            "screener_result": {"top20": [], "error": str(e)},
            "errors": errors,
        }


async def review_node(state: EventDrivenState) -> EventDrivenState:
    """Agent 3：收盘复盘"""
    try:
        result = await run_review_agent()
        return {**state, "review_result": result, "is_complete": True}
    except Exception as e:
        errors = list(state.get("errors", []))
        errors.append(f"review_node error: {str(e)}")
        return {
            **state,
            "review_result": {"error": str(e)},
            "errors": errors,
            "is_complete": True,
        }


# ─── 条件边函数 ──────────────────────────────────────────────────────────────

def should_run_screener(state: EventDrivenState) -> str:
    """
    条件边：判断是否执行精筛

    - run_mode == "trigger_only" → 直接结束
    - trigger_result.triggered == False → 直接结束
    - 否则 → 进入 screener
    """
    run_mode = state.get("run_mode", "full")

    if run_mode == "trigger_only":
        return "end"

    trigger_result = state.get("trigger_result", {})
    if not trigger_result.get("triggered", False):
        return "end"

    return "screener"


def should_run_review(state: EventDrivenState) -> str:
    """条件边：精筛完成后是否运行复盘（full模式才跑review）"""
    run_mode = state.get("run_mode", "full")
    if run_mode == "full":
        return "review"
    return "end"


# ─── 构建工作流 ──────────────────────────────────────────────────────────────

def _build_event_workflow() -> StateGraph:
    workflow = StateGraph(EventDrivenState)

    # 添加节点
    workflow.add_node("trigger", trigger_node)
    workflow.add_node("screener", screener_node)
    workflow.add_node("review", review_node)

    # 起点 → trigger
    workflow.add_edge(START, "trigger")

    # trigger → 条件边
    workflow.add_conditional_edges(
        "trigger",
        should_run_screener,
        {
            "screener": "screener",
            "end": END,
        },
    )

    # screener → 条件边
    workflow.add_conditional_edges(
        "screener",
        should_run_review,
        {
            "review": "review",
            "end": END,
        },
    )

    # review → END
    workflow.add_edge("review", END)

    return workflow.compile()


# 编译后的工作流实例（懒加载）
_compiled_workflow = None


def get_event_workflow():
    global _compiled_workflow
    if _compiled_workflow is None:
        _compiled_workflow = _build_event_workflow()
    return _compiled_workflow


# ─── 便捷入口 ────────────────────────────────────────────────────────────────

async def run_event_pipeline(run_mode: str = "full") -> dict[str, Any]:
    """
    运行事件驱动三层流水线

    Args:
        run_mode: "full" | "trigger_only" | "review_only"

    Returns:
        最终状态字典
    """
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")

    if run_mode == "review_only":
        # 直接执行 Agent 3，跳过 1/2
        result = await run_review_agent()
        return {
            "run_mode": run_mode,
            "date": date_str,
            "review_result": result,
            "is_complete": True,
            "errors": [],
        }

    workflow = get_event_workflow()
    initial_state: EventDrivenState = {
        "run_mode": run_mode,
        "date": date_str,
        "errors": [],
        "is_complete": False,
        "trigger_result": None,
        "screener_result": None,
        "review_result": None,
    }

    final_state = await workflow.ainvoke(initial_state)
    return final_state


async def run_review_only() -> dict[str, Any]:
    """便捷函数：仅运行收盘复盘"""
    return await run_event_pipeline("review_only")
