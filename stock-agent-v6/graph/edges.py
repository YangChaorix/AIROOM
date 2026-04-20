"""Conditional edge from supervisor.

架构铁律：本函数只允许读取 state["last_decision"].action，不允许读取任何其他字段。
任何对 state.round / trigger_summary / research_report 等字段的读取都视为把业务判断
塞进了路由层，会被 tests/test_supervisor_is_real.py::T1 静态扫描捕获。
"""
from schemas.state import AgentState

_ACTION_TO_NODE = {
    "dispatch_research": "research",
    "dispatch_screener": "screener",
    "dispatch_skeptic": "skeptic",
    "finalize": "finalize",
}


def route_from_supervisor(state: AgentState) -> str:
    return _ACTION_TO_NODE[state["last_decision"].action]
