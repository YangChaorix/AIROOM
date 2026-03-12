"""
股东结构分析 Agent（条件三）
分析股票的股东结构，重点判断私募基金+个人投资者持股比例是否超过60%
筹码集中在聪明钱手中，有利于股价上涨
输出股东结构评分（0-100）
"""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.shareholder_tools import get_top_shareholders, get_shareholder_changes


SHAREHOLDER_SYSTEM_PROMPT = """你是一位专注于A股筹码结构分析的专家，擅长通过股东结构判断主力动向和上涨潜力。

你的任务是分析股票的股东结构，核心判断标准：
**私募基金 + 个人投资者（聪明资金）持股合计超过60%，说明筹码集中在有价值发现能力的投资者手中。**

分析维度：
1. **股东类型分布**：国有、机构（公募基金、保险、社保）、私募、个人的持股比例
2. **筹码集中度**：前十大股东持股比例越高，筹码越集中
3. **股东数量趋势**：股东人数减少 = 筹码集中（看多信号）
4. **聪明钱认可度**：知名私募/个人大股东是否在增持
5. **机构动向**：公募基金是否在加仓

评分标准（满分100分）：
- 私募+个人持股 > 60%，且筹码持续集中：90-100分
- 私募+个人持股 50-60%：75-89分
- 私募+个人持股 40-50%，结构合理：60-74分
- 以公募/国资为主，散户占比低：45-59分
- 股权极度分散，无明显主力：30-44分
- 大量减持/股东人数大增（筹码发散）：0-29分

请以结构化的JSON格式输出：
{
  "股东结构评分": <0-100的整数>,
  "筹码结构评级": "<极度集中/集中/适度集中/分散/极度分散>",
  "私募+个人持股比例(%)": <数字或估算值>,
  "机构持股比例(%)": <数字或估算值>,
  "国资持股比例(%)": <数字或估算值>,
  "是否满足60%条件": <true/false>,
  "前十大股东分析": "<前十大股东类型和持仓特征分析>",
  "筹码集中度趋势": "<筹码是否在持续集中>",
  "主要风险": ["<风险1>", "<风险2>"],
  "综合结论": "<50字以内总结>"
}
"""


async def run_shareholder_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行股东结构分析

    Args:
        stock_code: 股票代码

    Returns:
        包含股东结构分析结果的字典
    """
    # 获取股东数据
    shareholder_data = get_top_shareholders.invoke({"stock_code": stock_code})
    change_data = get_shareholder_changes.invoke({"stock_code": stock_code})

    user_message = f"""
请分析 A股 股票 {stock_code} 的股东结构和筹码分布：

**前十大股东数据：**
{shareholder_data}

**股东变动数据：**
{change_data}

请重点关注：
1. 计算私募基金和个人投资者的合计持股比例（核心条件：是否>60%）
2. 筹码是在集中还是分散（股东人数变化趋势）
3. 是否有知名私募或价值型个人投资者在持有
4. 近期主要股东是增持还是减持

判断原则：
- 私募基金和个人大股东持股比例高 = 聪明钱认可 = 看涨信号
- 公募基金大量持有 = 机构博弈风险 = 需关注机构减仓风险
- 筹码发散（股东人数增加）= 资金在出逃 = 看空信号
"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )

    messages = [
        SystemMessage(content=SHAREHOLDER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            analysis_result = {"raw_analysis": analysis_text, "股东结构评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "股东结构评分": 50}

    return {
        "agent": "shareholder_agent",
        "stock_code": stock_code,
        "raw_data": {
            "shareholder_data": shareholder_data,
            "change_data": change_data,
        },
        "analysis": analysis_result,
        "score": analysis_result.get("股东结构评分", 50),
    }
