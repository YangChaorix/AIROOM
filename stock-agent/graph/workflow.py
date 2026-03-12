"""
LangGraph 工作流定义
7个专项分析Agent并行执行，最终由Supervisor汇总打分

工作流结构：
START → parallel_7_analysis → supervisor → END

7个并行分析节点：
1. policy_node（政策分析，权重20%）
2. industry_leader_node（行业龙头，权重15%）
3. shareholder_node（股东结构，权重15%）
4. supply_demand_node（供需涨价，权重20%）
5. trend_node（中长期趋势，权重10%）
6. catalyst_node（转折催化剂，权重10%）
7. technical_node（技术量能，权重10%）
"""

import asyncio
import traceback
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph

from agents.policy_agent import run_policy_analysis
from agents.industry_leader_agent import run_industry_leader_analysis
from agents.shareholder_agent import run_shareholder_analysis
from agents.supply_demand_agent import run_supply_demand_analysis
from agents.trend_agent import run_trend_analysis
from agents.catalyst_agent import run_catalyst_analysis
from agents.technical_agent import run_technical_analysis
from agents.supervisor_agent import run_supervisor_analysis


# ==================== State 定义 ====================

class StockAnalysisState(TypedDict):
    """
    LangGraph 工作流的状态定义
    包含7个选股条件的分析结果
    """
    stock_code: str

    # 7个条件对应的Agent分析结果
    policy_result: Optional[dict[str, Any]]           # 条件一：政策支持
    industry_result: Optional[dict[str, Any]]         # 条件二：行业龙头
    shareholder_result: Optional[dict[str, Any]]      # 条件三：股东结构
    supply_demand_result: Optional[dict[str, Any]]    # 条件四：供需涨价
    trend_result: Optional[dict[str, Any]]            # 条件五：中长期趋势
    catalyst_result: Optional[dict[str, Any]]         # 条件六：转折催化剂
    technical_result: Optional[dict[str, Any]]        # 条件七：技术量能

    # Supervisor最终汇总
    supervisor_result: Optional[dict[str, Any]]

    # 执行状态
    errors: list[str]
    is_complete: bool


# ==================== 并行分析节点 ====================

def _make_default_result(agent_name: str, stock_code: str, error: str, score_key: str) -> dict:
    """创建分析失败时的默认结果"""
    return {
        "agent": agent_name,
        "stock_code": stock_code,
        "error": error,
        "score": 50,
        "analysis": {score_key: 50, "综合结论": f"分析失败：{error}"},
    }


async def parallel_7_analysis_node(state: StockAnalysisState) -> dict[str, Any]:
    """
    并行执行7个专项分析节点
    使用 asyncio.gather 最大化并行度，减少总分析时间
    """
    stock_code = state["stock_code"]
    print(f"\n{'='*60}")
    print(f"[7维度并行分析] 开始分析股票 {stock_code}")
    print(f"运行7个专项Agent：政策/龙头/股东/供需/趋势/催化剂/技术")
    print(f"{'='*60}")

    # 并行执行7个分析任务
    tasks = [
        run_policy_analysis(stock_code),
        run_industry_leader_analysis(stock_code),
        run_shareholder_analysis(stock_code),
        run_supply_demand_analysis(stock_code),
        run_trend_analysis(stock_code),
        run_catalyst_analysis(stock_code),
        run_technical_analysis(stock_code),
    ]

    agent_configs = [
        ("policy", "政策分析", "政策评分"),
        ("industry", "行业龙头", "行业地位评分"),
        ("shareholder", "股东结构", "股东结构评分"),
        ("supply_demand", "供需涨价", "供需评分"),
        ("trend", "中长期趋势", "趋势评分"),
        ("catalyst", "转折催化剂", "催化剂评分"),
        ("technical", "技术量能", "技术面评分"),
    ]

    errors = state.get("errors", [])
    results = await asyncio.gather(*tasks, return_exceptions=True)

    result_map = {}
    for i, (result, (key, name, score_key)) in enumerate(zip(results, agent_configs)):
        if isinstance(result, Exception):
            error_msg = f"{name}分析失败: {str(result)}"
            errors.append(error_msg)
            print(f"[{name}] 失败：{error_msg[:80]}")
            result_map[f"{key}_result"] = _make_default_result(
                f"{key}_agent", stock_code, str(result), score_key
            )
        else:
            score = result.get("score", "N/A")
            print(f"[{name}] 完成，评分：{score}/100")
            result_map[f"{key}_result"] = result

    return {**result_map, "errors": errors}


# ==================== Supervisor节点 ====================

async def supervisor_node(state: StockAnalysisState) -> dict[str, Any]:
    """
    Supervisor汇总节点
    汇总7个子Agent结果，给出综合评分和最终建议
    """
    stock_code = state["stock_code"]
    errors = state.get("errors", [])

    print(f"\n[主控分析] 开始汇总 {stock_code} 的7维度综合分析...")

    # 获取各Agent结果（提供默认值）
    def _default(score_key: str) -> dict:
        return {"score": 50, "analysis": {score_key: 50, "综合结论": "数据缺失"}}

    policy_result = state.get("policy_result") or _default("政策评分")
    industry_result = state.get("industry_result") or _default("行业地位评分")
    shareholder_result = state.get("shareholder_result") or _default("股东结构评分")
    supply_demand_result = state.get("supply_demand_result") or _default("供需评分")
    trend_result = state.get("trend_result") or _default("趋势评分")
    catalyst_result = state.get("catalyst_result") or _default("催化剂评分")
    technical_result = state.get("technical_result") or _default("技术面评分")

    try:
        supervisor_result = await run_supervisor_analysis(
            stock_code=stock_code,
            policy_result=policy_result,
            industry_result=industry_result,
            shareholder_result=shareholder_result,
            supply_demand_result=supply_demand_result,
            trend_result=trend_result,
            catalyst_result=catalyst_result,
            technical_result=technical_result,
        )
        final_score = supervisor_result.get("score", "N/A")
        print(f"[主控分析] {stock_code} 综合分析完成，最终评分：{final_score}/100")

        return {
            "supervisor_result": supervisor_result,
            "is_complete": True,
            "errors": errors,
        }
    except Exception as e:
        error_msg = f"主控分析失败: {str(e)}\n{traceback.format_exc()}"
        errors.append(error_msg)
        print(f"[主控分析] 错误：{str(e)[:100]}")

        # 计算简单加权分作为备用
        fallback_score = round(
            policy_result.get("score", 50) * 0.20
            + industry_result.get("score", 50) * 0.15
            + shareholder_result.get("score", 50) * 0.15
            + supply_demand_result.get("score", 50) * 0.20
            + trend_result.get("score", 50) * 0.10
            + catalyst_result.get("score", 50) * 0.10
            + technical_result.get("score", 50) * 0.10
        )

        return {
            "supervisor_result": {
                "error": str(e),
                "score": fallback_score,
                "final_report": {"综合得分": fallback_score, "股票代码": stock_code},
                "sub_scores": {
                    "policy": policy_result.get("score", 50),
                    "industry": industry_result.get("score", 50),
                    "shareholder": shareholder_result.get("score", 50),
                    "supply_demand": supply_demand_result.get("score", 50),
                    "trend": trend_result.get("score", 50),
                    "catalyst": catalyst_result.get("score", 50),
                    "technical": technical_result.get("score", 50),
                    "weighted_total": fallback_score,
                },
            },
            "is_complete": True,
            "errors": errors,
        }


# ==================== 工作流构建 ====================

def create_workflow() -> StateGraph:
    """
    创建并配置7Agent LangGraph StateGraph工作流

    Returns:
        编译好的 LangGraph 工作流
    """
    workflow = StateGraph(StockAnalysisState)

    # 添加节点
    workflow.add_node("parallel_7_analysis", parallel_7_analysis_node)
    workflow.add_node("supervisor", supervisor_node)

    # 定义执行流程
    workflow.set_entry_point("parallel_7_analysis")
    workflow.add_edge("parallel_7_analysis", "supervisor")
    workflow.add_edge("supervisor", END)

    return workflow.compile()


async def run_stock_analysis(stock_code: str) -> dict[str, Any]:
    """
    运行单只股票的完整7维度分析流程

    Args:
        stock_code: 股票代码（如 '000001'）

    Returns:
        包含完整分析结果的字典
    """
    initial_state: StockAnalysisState = {
        "stock_code": stock_code,
        "policy_result": None,
        "industry_result": None,
        "shareholder_result": None,
        "supply_demand_result": None,
        "trend_result": None,
        "catalyst_result": None,
        "technical_result": None,
        "supervisor_result": None,
        "errors": [],
        "is_complete": False,
    }

    workflow = create_workflow()

    print(f"\n{'='*60}")
    print(f"开始7维度分析股票：{stock_code}")
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
