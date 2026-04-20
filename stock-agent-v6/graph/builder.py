"""LangGraph builder.

Entry = supervisor。每个子节点完成后回到 supervisor 再次决策。
finalize 节点渲染 Markdown 并结束图。
"""
from langgraph.graph import END, StateGraph

from agents.research import research_node
from agents.screener import screener_node
from agents.skeptic import skeptic_node
from agents.supervisor import supervisor_node
from graph.edges import route_from_supervisor
from render.markdown_report import finalize_node
from schemas.state import AgentState


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("supervisor", supervisor_node)
    g.add_node("research", research_node)
    g.add_node("screener", screener_node)
    g.add_node("skeptic", skeptic_node)
    g.add_node("finalize", finalize_node)

    g.set_entry_point("supervisor")

    g.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "research": "research",
            "screener": "screener",
            "skeptic": "skeptic",
            "finalize": "finalize",
        },
    )

    g.add_edge("research", "supervisor")
    g.add_edge("screener", "supervisor")
    g.add_edge("skeptic", "supervisor")
    g.add_edge("finalize", END)

    return g.compile()
