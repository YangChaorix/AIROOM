"""
政策分析 Agent（条件一）
分析是否有新政策支持该股票所在行业
输出政策评分（0-100）和政策分析报告
"""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.news_tools import get_stock_news


POLICY_SYSTEM_PROMPT = """你是一位专注于A股政策分析的专家，擅长解读国家政策对行业和个股的影响。

你的任务是分析该股票所在行业是否有新政策支持，包括：
1. **产业政策**：国家/地方政府对该行业的扶持政策、补贴、税收优惠
2. **监管政策**：行业监管是否宽松/严格，对龙头企业是否有利
3. **行业规划**：五年规划、专项发展规划中是否涉及该行业
4. **政策时效**：政策是否是近期（6个月内）出台的新政策

评分标准（满分100分，基准50分）：
- 有明确国家级重大政策支持：+30分
- 有地方政府扶持政策：+15分
- 行业处于政策监管宽松期：+10分
- 五年规划重点行业：+15分
- 无明确政策支持：维持50分
- 受到政策收紧或监管打压：-20至-40分

请以结构化的JSON格式输出分析结果：
{
  "政策评分": <0-100的整数>,
  "政策支持等级": "<强力支持/一般支持/中性/轻度压制/严重压制>",
  "所属行业": "<行业名称>",
  "近期相关政策": [
    {"政策名称": "<>", "发布时间": "<>", "影响方向": "<正面/负面/中性>", "重要程度": "<高/中/低>"}
  ],
  "政策分析": "<详细分析政策对行业和个股的影响>",
  "政策催化剂": "<未来可能出台的政策及其影响预测>",
  "政策风险": "<政策面的主要风险点>",
  "综合结论": "<50字以内总结>"
}
"""


async def run_policy_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行政策面分析

    Args:
        stock_code: 股票代码

    Returns:
        包含政策分析结果的字典
    """
    # 获取新闻和公告数据（用于政策分析）
    news_data = get_stock_news.invoke({"stock_code": stock_code})

    user_message = f"""
请分析 A股 股票 {stock_code} 所在行业的政策面情况：

**近期相关新闻和公告（用于判断政策动向）：**
{news_data}

请重点关注：
1. 新闻中是否有政府政策、监管文件、行业规划的相关报道
2. 该行业是否处于国家重点支持领域（如新能源、AI、半导体、医疗、消费升级等）
3. 近6个月内是否有新政策出台（利好或利空）
4. 行业监管环境是否友好

注意：如果新闻中政策信息不足，请基于行业基本情况给出合理判断，并说明依据。
"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )

    messages = [
        SystemMessage(content=POLICY_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            analysis_result = {"raw_analysis": analysis_text, "政策评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "政策评分": 50}

    return {
        "agent": "policy_agent",
        "stock_code": stock_code,
        "raw_data": {"news_data": news_data},
        "analysis": analysis_result,
        "score": analysis_result.get("政策评分", 50),
    }
