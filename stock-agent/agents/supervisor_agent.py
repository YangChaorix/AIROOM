"""
主控 Supervisor Agent（架构 B：ReAct Agent）
通过 Tool Calling 动态决定调用哪些子 Agent，根据股票类型自适应调整分析策略和权重。

流程：
1. 调用 get_stock_basic_info 了解股票类型（国企/金融/小盘/民企）
2. 根据类型动态选择并调用相关子 Agent 工具
3. 汇总所有工具返回结果，输出最终 JSON 分析报告
"""

import json
import re
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from config.settings import settings
from tools.stock_data import get_stock_basic_info
from agents.sub_agent_tools import (
    policy_analysis_tool,
    industry_leader_tool,
    shareholder_analysis_tool,
    supply_demand_tool,
    trend_tool,
    catalyst_tool,
    technical_tool,
)


SUPERVISOR_SYSTEM_PROMPT = """你是一位资深的A股投资顾问，负责综合多维度专项分析，给出最终投资建议。

## 分析流程

**第一步**：调用 get_stock_basic_info 获取股票的行业、市值、性质等基础信息。

**第二步**：根据股票类型，决定重点分析维度和权重：

| 股票类型 | 判断标准 | 权重分配 | 跳过项 |
|---------|---------|---------|-------|
| 国企/央企大盘 | 实控人为国资委/地方国资 | 政策30% + 龙头20% + 供需20% + 趋势15% + 催化剂10% + 技术5% | 股东结构 |
| 金融股 | 行业为银行/保险/券商/信托 | 政策35% + 龙头20% + 趋势15% + 催化剂10% + 技术10% + 股东10% | 供需分析 |
| 民企小盘 | 民营企业且流通市值<50亿 | 股东25% + 供需20% + 催化剂20% + 政策15% + 趋势10% + 技术10% | 行业龙头 |
| 民企中大盘（默认） | 其他情况 | 政策20% + 供需20% + 股东15% + 龙头15% + 趋势10% + 催化剂10% + 技术10% | 无 |

**第三步**：并行调用选定的分析工具（可同时发起多个 tool call）。

**第四步**：汇总所有工具结果，输出以下 JSON 格式的完整投资报告。

## 输出格式（必须严格遵守）

最终回复必须是且仅是一个合法的 JSON 对象，格式如下：
{
  "股票代码": "<代码>",
  "分析日期": "<日期>",
  "股票类型": "<国企央企大盘/金融股/民企小盘/民企中大盘>",
  "分析维度": ["policy", "industry", "shareholder", "supply_demand", "trend", "catalyst", "technical"],
  "综合得分": <0-100的整数>,
  "投资评级": "<★~★★★★★>",
  "评级说明": "<强烈推荐/推荐/观望/谨慎/回避>",

  "7条件达标情况": {
    "条件一_政策支持": {"得分": <分或null>, "是否达标": <true/false/null>, "简评": "<评语或'未分析'>"},
    "条件二_行业龙头": {"得分": <分或null>, "是否达标": <true/false/null>, "简评": "<评语或'未分析'>"},
    "条件三_股东结构": {"得分": <分或null>, "是否达标": <true/false/null>, "简评": "<评语或'未分析'>"},
    "条件四_供需涨价": {"得分": <分或null>, "是否达标": <true/false/null>, "简评": "<评语或'未分析'>"},
    "条件五_中长期趋势": {"得分": <分或null>, "是否达标": <true/false/null>, "简评": "<评语或'未分析'>"},
    "条件六_催化剂": {"得分": <分或null>, "是否达标": <true/false/null>, "简评": "<评语或'未分析'>"},
    "条件七_技术量能": {"得分": <分或null>, "是否达标": <true/false/null>, "简评": "<评语或'未分析'>"}
  },

  "加权评分明细": {
    "政策评分": <分或null>, "政策权重": "<百分比或'跳过'>", "政策加权分": <加权分或0>,
    "龙头评分": <分或null>, "龙头权重": "<百分比或'跳过'>", "龙头加权分": <加权分或0>,
    "股东评分": <分或null>, "股东权重": "<百分比或'跳过'>", "股东加权分": <加权分或0>,
    "供需评分": <分或null>, "供需权重": "<百分比或'跳过'>", "供需加权分": <加权分或0>,
    "趋势评分": <分或null>, "趋势权重": "<百分比或'跳过'>", "趋势加权分": <加权分或0>,
    "催化剂评分": <分或null>, "催化剂权重": "<百分比或'跳过'>", "催化剂加权分": <加权分或0>,
    "技术评分": <分或null>, "技术权重": "<百分比或'跳过'>", "技术加权分": <加权分或0>
  },

  "核心投资逻辑": "<3-5句话说明为何值得关注或回避>",
  "最强逻辑": "<该股票最核心的投资逻辑（1-2句话）>",
  "主要优势": ["<优势1>", "<优势2>", "<优势3>"],
  "主要风险": ["<风险1>", "<风险2>", "<风险3>"],

  "操作建议": {
    "建议": "<买入/关注/观望/减持/回避>",
    "参考买入区间": "<价格区间或'暂不建议买入'>",
    "参考止损位": "<价格或比例>",
    "参考目标价": "<价格区间或'暂无明确目标'>",
    "持仓周期": "<短期(1个月内)/中期(1-6个月)/长期(6个月以上)/暂不持有>",
    "仓位建议": "<轻仓(10-20%)/标准仓(20-30%)/重仓(30-50%)/不建议持有>"
  },

  "分析摘要": "<200字以内的完整分析摘要>"
}

## 投资评级标准
- 85-100分：★★★★★ 强烈推荐
- 70-84分：★★★★ 推荐
- 55-69分：★★★ 观望
- 40-54分：★★ 谨慎
- 0-39分：★ 回避

## 重要提醒
1. 投资有风险，以上分析仅供参考，不构成投资建议
2. 跳过的维度在对应字段填入 null（得分）或 "跳过"（权重），加权分填0
3. 综合得分基于实际分析的维度加权计算，确保权重之和为100%
"""


async def run_supervisor_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行 Supervisor ReAct Agent 综合分析

    Args:
        stock_code: 股票代码

    Returns:
        包含最终综合报告的字典（兼容原有格式）
    """
    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=0.1,
    )

    tools = [
        get_stock_basic_info,
        policy_analysis_tool,
        industry_leader_tool,
        shareholder_analysis_tool,
        supply_demand_tool,
        trend_tool,
        catalyst_tool,
        technical_tool,
    ]

    agent = create_react_agent(llm, tools, prompt=SUPERVISOR_SYSTEM_PROMPT)
    result = await agent.ainvoke({"messages": [("user", f"请分析股票 {stock_code}")]})

    # 提取最后一条 AI 消息
    final_msg = result["messages"][-1].content

    try:
        json_match = re.search(r'\{[\s\S]*\}', final_msg)
        if json_match:
            final_report = json.loads(json_match.group())
        else:
            final_report = {
                "raw_analysis": final_msg,
                "综合得分": 50,
                "股票代码": stock_code,
            }
    except json.JSONDecodeError:
        final_report = {
            "raw_analysis": final_msg,
            "综合得分": 50,
            "股票代码": stock_code,
        }

    # 从加权评分明细中提取各维度分数，兼容原有 sub_scores 格式
    detail = final_report.get("加权评分明细", {})
    sub_scores = {
        "policy":       _to_score(detail.get("政策评分")),
        "industry":     _to_score(detail.get("龙头评分")),
        "shareholder":  _to_score(detail.get("股东评分")),
        "supply_demand": _to_score(detail.get("供需评分")),
        "trend":        _to_score(detail.get("趋势评分")),
        "catalyst":     _to_score(detail.get("催化剂评分")),
        "technical":    _to_score(detail.get("技术评分")),
        "weighted_total": float(final_report.get("综合得分", 50)),
    }

    return {
        "agent": "supervisor_agent",
        "stock_code": stock_code,
        "sub_scores": sub_scores,
        "final_report": final_report,
        "score": final_report.get("综合得分", 50),
    }


def _to_score(value: Any) -> float:
    """将评分值安全转换为 float，None/null 返回 0"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def create_supervisor_agent() -> None:
    """兼容性占位函数"""
    pass
