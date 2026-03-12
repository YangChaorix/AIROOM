"""
主控 Supervisor Agent
汇总7个子Agent的分析结果，进行综合打分（满分100分）并输出最终选股建议

权重分配：
- PolicyAgent（政策分析）：20%
- IndustryLeaderAgent（行业龙头）：15%
- ShareholderAgent（股东结构）：15%
- SupplyDemandAgent（供需涨价）：20%
- TrendAgent（中长期趋势）：10%
- CatalystAgent（转折催化剂）：10%
- TechnicalAgent（技术量能）：10%
"""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings


SUPERVISOR_SYSTEM_PROMPT = """你是一位资深的A股投资顾问，负责综合7个维度的专项分析，给出最终投资建议。

你将收到7个专业子分析师的报告，每个报告对应一个核心选股条件：
1. 政策分析（权重20%）：新政策支持行业
2. 行业龙头（权重15%）：是否为行业龙头企业
3. 股东结构（权重15%）：私募+个人持股>60%
4. 供需涨价（权重20%）：产品涨价+供需不平衡
5. 中长期趋势（权重10%）：未来半年~2年上涨趋势
6. 转折催化剂（权重10%）：存在明确的转折催化事件
7. 技术量能（权重10%）：技术指标确认买点

综合评分计算：
综合分 = 政策×20% + 龙头×15% + 股东×15% + 供需×20% + 趋势×10% + 催化剂×10% + 技术×10%

投资评级：
- 85-100分：★★★★★ 强烈推荐（7个条件高度匹配）
- 70-84分：★★★★ 推荐（多数条件匹配）
- 55-69分：★★★ 观望（部分条件匹配）
- 40-54分：★★ 谨慎（条件匹配度低）
- 0-39分：★ 回避（大部分条件不满足）

请以结构化的JSON格式输出最终分析报告：
{
  "股票代码": "<代码>",
  "分析日期": "<日期>",
  "综合得分": <0-100的整数>,
  "投资评级": "<★~★★★★★>",
  "评级说明": "<强烈推荐/推荐/观望/谨慎/回避>",

  "7条件达标情况": {
    "条件一_政策支持": {"得分": <分>, "是否达标": <true/false>, "简评": "<>"},
    "条件二_行业龙头": {"得分": <分>, "是否达标": <true/false>, "简评": "<>"},
    "条件三_股东结构": {"得分": <分>, "是否达标": <true/false>, "简评": "<>"},
    "条件四_供需涨价": {"得分": <分>, "是否达标": <true/false>, "简评": "<>"},
    "条件五_中长期趋势": {"得分": <分>, "是否达标": <true/false>, "简评": "<>"},
    "条件六_催化剂": {"得分": <分>, "是否达标": <true/false>, "简评": "<>"},
    "条件七_技术量能": {"得分": <分>, "是否达标": <true/false>, "简评": "<>"}
  },

  "加权评分明细": {
    "政策评分": <分>, "政策权重": "20%", "政策加权分": <分×0.2>,
    "龙头评分": <分>, "龙头权重": "15%", "龙头加权分": <分×0.15>,
    "股东评分": <分>, "股东权重": "15%", "股东加权分": <分×0.15>,
    "供需评分": <分>, "供需权重": "20%", "供需加权分": <分×0.2>,
    "趋势评分": <分>, "趋势权重": "10%", "趋势加权分": <分×0.1>,
    "催化剂评分": <分>, "催化剂权重": "10%", "催化剂加权分": <分×0.1>,
    "技术评分": <分>, "技术权重": "10%", "技术加权分": <分×0.1>
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

  "分析摘要": "<200字以内的完整分析摘要，覆盖7个条件的综合评价>"
}

重要提醒：
1. 投资有风险，以上分析仅供参考，不构成投资建议
2. 7个条件全部达标（每条≥65分）时才能强烈推荐
3. 如有条件严重不达标（<40分），需在报告中特别提示
"""


async def run_supervisor_analysis(
    stock_code: str,
    policy_result: dict[str, Any],
    industry_result: dict[str, Any],
    shareholder_result: dict[str, Any],
    supply_demand_result: dict[str, Any],
    trend_result: dict[str, Any],
    catalyst_result: dict[str, Any],
    technical_result: dict[str, Any],
) -> dict[str, Any]:
    """
    执行综合汇总分析

    Args:
        stock_code: 股票代码
        policy_result: 政策分析结果
        industry_result: 行业龙头分析结果
        shareholder_result: 股东结构分析结果
        supply_demand_result: 供需涨价分析结果
        trend_result: 中长期趋势分析结果
        catalyst_result: 转折催化剂分析结果
        technical_result: 技术量能分析结果

    Returns:
        包含最终综合报告的字典
    """
    from datetime import datetime

    # 提取各维度评分
    policy_score = policy_result.get("score", 50)
    industry_score = industry_result.get("score", 50)
    shareholder_score = shareholder_result.get("score", 50)
    supply_demand_score = supply_demand_result.get("score", 50)
    trend_score = trend_result.get("score", 50)
    catalyst_score = catalyst_result.get("score", 50)
    technical_score = technical_result.get("score", 50)

    # 计算加权综合分
    weighted_score = (
        policy_score * 0.20
        + industry_score * 0.15
        + shareholder_score * 0.15
        + supply_demand_score * 0.20
        + trend_score * 0.10
        + catalyst_score * 0.10
        + technical_score * 0.10
    )

    user_message = f"""
请对以下 A股 股票 {stock_code} 的7维度分析进行综合评估，输出最终投资报告：

**条件一 - 政策分析（权重20%，评分：{policy_score}/100）：**
{json.dumps(policy_result.get('analysis', {}), ensure_ascii=False, indent=2)}

**条件二 - 行业龙头（权重15%，评分：{industry_score}/100）：**
{json.dumps(industry_result.get('analysis', {}), ensure_ascii=False, indent=2)}

**条件三 - 股东结构（权重15%，评分：{shareholder_score}/100）：**
{json.dumps(shareholder_result.get('analysis', {}), ensure_ascii=False, indent=2)}

**条件四 - 供需涨价（权重20%，评分：{supply_demand_score}/100）：**
{json.dumps(supply_demand_result.get('analysis', {}), ensure_ascii=False, indent=2)}

**条件五 - 中长期趋势（权重10%，评分：{trend_score}/100）：**
{json.dumps(trend_result.get('analysis', {}), ensure_ascii=False, indent=2)}

**条件六 - 转折催化剂（权重10%，评分：{catalyst_score}/100）：**
{json.dumps(catalyst_result.get('analysis', {}), ensure_ascii=False, indent=2)}

**条件七 - 技术量能（权重10%，评分：{technical_score}/100）：**
{json.dumps(technical_result.get('analysis', {}), ensure_ascii=False, indent=2)}

**预计算加权综合分（参考）：{round(weighted_score, 1)} 分**
分析日期：{datetime.now().strftime('%Y-%m-%d')}

请按照系统提示的JSON格式输出最终投资报告。
特别注意：
1. 综合得分可在加权分基础上±5分调整，需说明原因
2. 如有单项严重不达标（<40分），必须在报告中特别说明
3. 操作建议要具体可行，包含明确的价格参考
"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=0.2,
        max_tokens=settings.deepseek.max_tokens,
    )

    messages = [
        SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            final_report = json.loads(json_match.group())
        else:
            final_report = {
                "raw_analysis": analysis_text,
                "综合得分": round(weighted_score, 0),
                "股票代码": stock_code,
            }
    except json.JSONDecodeError:
        final_report = {
            "raw_analysis": analysis_text,
            "综合得分": round(weighted_score, 0),
            "股票代码": stock_code,
        }

    return {
        "agent": "supervisor_agent",
        "stock_code": stock_code,
        "sub_scores": {
            "policy": policy_score,
            "industry": industry_score,
            "shareholder": shareholder_score,
            "supply_demand": supply_demand_score,
            "trend": trend_score,
            "catalyst": catalyst_score,
            "technical": technical_score,
            "weighted_total": round(weighted_score, 1),
        },
        "final_report": final_report,
        "score": final_report.get("综合得分", round(weighted_score, 0)),
    }


def create_supervisor_agent() -> None:
    """兼容性占位函数"""
    pass
