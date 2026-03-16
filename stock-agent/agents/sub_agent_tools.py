"""
子 Agent 工具包装模块
将 7 个子 Agent 的 run_*_analysis() 函数包装为 LangChain @tool，
供 Supervisor ReAct Agent 通过 Tool Calling 动态调用。
"""

import json

from langchain_core.tools import tool

from agents.policy_agent import run_policy_analysis
from agents.industry_leader_agent import run_industry_leader_analysis
from agents.shareholder_agent import run_shareholder_analysis
from agents.supply_demand_agent import run_supply_demand_analysis
from agents.trend_agent import run_trend_analysis
from agents.catalyst_agent import run_catalyst_analysis
from agents.technical_agent import run_technical_analysis


@tool
async def policy_analysis_tool(stock_code: str) -> str:
    """分析股票所在行业的政策支持情况，评分0-100。
    适用于所有股票，国企/央企及受政策影响行业（新能源、半导体、医疗等）权重更高。"""
    result = await run_policy_analysis(stock_code)
    return json.dumps(result, ensure_ascii=False)


@tool
async def industry_leader_tool(stock_code: str) -> str:
    """分析股票是否为行业龙头企业，评分0-100。
    大盘股/国企该项权重更高；民企小盘股（流通市值<50亿）可降低权重或跳过。"""
    result = await run_industry_leader_analysis(stock_code)
    return json.dumps(result, ensure_ascii=False)


@tool
async def shareholder_analysis_tool(stock_code: str) -> str:
    """分析股票股东结构，判断私募+个人持股是否超60%，评分0-100。
    国企/金融股（银行/保险/券商）此项意义较小，可跳过。"""
    result = await run_shareholder_analysis(stock_code)
    return json.dumps(result, ensure_ascii=False)


@tool
async def supply_demand_tool(stock_code: str) -> str:
    """分析股票产品涨价趋势和供需不平衡情况，评分0-100。
    金融股（银行/保险/券商）此项意义较小，可跳过。"""
    result = await run_supply_demand_analysis(stock_code)
    return json.dumps(result, ensure_ascii=False)


@tool
async def trend_tool(stock_code: str) -> str:
    """分析股票中长期（未来半年至2年）上涨趋势，评分0-100。
    适用于所有股票类型。"""
    result = await run_trend_analysis(stock_code)
    return json.dumps(result, ensure_ascii=False)


@tool
async def catalyst_tool(stock_code: str) -> str:
    """分析股票是否存在明确的转折催化剂事件（业绩爆发、并购重组、新产品发布等），评分0-100。
    适用于所有股票类型，民企小盘股该项权重更高。"""
    result = await run_catalyst_analysis(stock_code)
    return json.dumps(result, ensure_ascii=False)


@tool
async def technical_tool(stock_code: str) -> str:
    """分析股票技术指标和量能形态，确认买点信号，评分0-100。
    适用于所有股票类型。"""
    result = await run_technical_analysis(stock_code)
    return json.dumps(result, ensure_ascii=False)
