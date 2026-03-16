"""
LangGraph 工作流定义（架构 B：Supervisor Tool Calling）

工作流结构：
START → supervisor → END

Supervisor 是 ReAct Agent，内部通过 Tool Calling 动态决定调用哪些子 Agent：
1. 先调用 get_stock_basic_info 了解股票类型
2. 根据类型自适应选择并（并行）调用子 Agent 工具
3. 汇总结果输出最终报告
"""

import asyncio
import traceback
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.supervisor_agent import run_supervisor_analysis


# ==================== State 定义 ====================

class StockAnalysisState(TypedDict):
    """LangGraph 工作流的状态定义"""
    stock_code: str
    supervisor_result: Optional[dict[str, Any]]  # Supervisor 直接输出完整结果
    errors: list[str]
    is_complete: bool


# ==================== Supervisor 节点 ====================

async def supervisor_node(state: StockAnalysisState) -> dict[str, Any]:
    """
    Supervisor ReAct Agent 节点
    动态调用子 Agent 工具，输出综合分析报告
    """
    stock_code = state["stock_code"]
    errors = state.get("errors", [])

    print(f"\n{'='*60}")
    print(f"[Supervisor] 开始分析股票 {stock_code}")
    print(f"[Supervisor] 将先获取基础信息，再自适应调用子 Agent")
    print(f"{'='*60}")

    try:
        supervisor_result = await run_supervisor_analysis(stock_code)
        final_score = supervisor_result.get("score", "N/A")
        stock_type = supervisor_result.get("final_report", {}).get("股票类型", "未知")
        print(f"\n[Supervisor] {stock_code} 分析完成")
        print(f"[Supervisor] 股票类型：{stock_type}")
        print(f"[Supervisor] 最终评分：{final_score}/100")

        return {
            "supervisor_result": supervisor_result,
            "is_complete": True,
            "errors": errors,
        }
    except Exception as e:
        error_msg = f"Supervisor 分析失败: {str(e)}\n{traceback.format_exc()}"
        errors.append(error_msg)
        print(f"[Supervisor] 错误：{str(e)[:100]}")

        return {
            "supervisor_result": {
                "error": str(e),
                "score": 0,
                "final_report": {"综合得分": 0, "股票代码": stock_code},
                "sub_scores": {},
            },
            "is_complete": True,
            "errors": errors,
        }


# ==================== 工作流构建 ====================

def create_workflow() -> StateGraph:
    """
    创建并配置 Supervisor ReAct Agent 工作流

    Returns:
        编译好的 LangGraph 工作流
    """
    workflow = StateGraph(StockAnalysisState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_edge(START, "supervisor")
    workflow.add_edge("supervisor", END)

    return workflow.compile()


async def run_stock_analysis(stock_code: str) -> dict[str, Any]:
    """
    运行单只股票的完整分析流程

    Args:
        stock_code: 股票代码（如 '000001'）

    Returns:
        包含完整分析结果的字典
    """
    initial_state: StockAnalysisState = {
        "stock_code": stock_code,
        "supervisor_result": None,
        "errors": [],
        "is_complete": False,
    }

    workflow = create_workflow()

    print(f"\n{'='*60}")
    print(f"开始分析股票：{stock_code}")
    print(f"{'='*60}")

    final_state = await workflow.ainvoke(initial_state)

    print(f"\n{'='*60}")
    print(f"股票 {stock_code} 分析完成")
    if final_state.get("errors"):
        print(f"分析过程中出现 {len(final_state['errors'])} 个警告/错误")
    print(f"{'='*60}\n")

    return final_state


async def run_batch_analysis(
    stock_codes: list[str],
    max_concurrent: int = 2,
) -> list[dict[str, Any]]:
    """
    批量分析多只股票

    Args:
        stock_codes: 股票代码列表
        max_concurrent: 最大并发分析数量（避免API限流）

    Returns:
        每只股票的分析结果列表
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def analyze_with_semaphore(code: str) -> dict[str, Any]:
        async with semaphore:
            return await run_stock_analysis(code)

    tasks = [analyze_with_semaphore(code) for code in stock_codes]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for i, result in enumerate(batch_results):
        if isinstance(result, Exception):
            results.append({
                "stock_code": stock_codes[i],
                "error": str(result),
                "is_complete": False,
            })
        else:
            results.append(result)

    return results
