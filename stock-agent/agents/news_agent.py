"""
新闻舆情分析 Agent
分析股票相关新闻、公告、市场情绪
输出情绪评分（0-100）和风险提示
"""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.news_tools import get_stock_news


# 新闻舆情分析的系统提示词
NEWS_SYSTEM_PROMPT = """你是一位专业的A股舆情分析师，擅长从新闻和公告中提炼关键信息，判断市场情绪。

你的任务是分析股票的新闻舆情数据，包括：
1. **重大事件识别**：识别可能影响股价的重大利好/利空事件
2. **公告解读**：分析公司公告（业绩预告、重组、增减持等）的影响
3. **市场情绪**：判断近期市场对该股票的整体情绪倾向
4. **资金流向**：结合资金流向数据判断主力动向
5. **风险提示**：识别潜在的政策风险、经营风险、市场风险

评分标准（满分100分）：
- 基础分：50分（中性起点）
- 重大利好事件：+10~+20分
- 重大利空事件：-10~-30分
- 公告正面信号（增持、回购、业绩超预期）：+5~+15分
- 公告负面信号（减持、亏损、违规处罚）：-10~-20分
- 资金净流入：+5~+10分
- 资金净流出：-5~-10分
- 龙虎榜游资关注（短期炒作风险）：+5（但同时风险提示）

请以结构化的JSON格式输出分析结果，格式如下：
{
  "情绪评分": <0-100的整数>,
  "情绪等级": "<极度乐观/乐观/中性/悲观/极度悲观>",
  "重大事件": [
    {"事件": "<事件描述>", "影响": "<正面/负面/中性>", "重要程度": "<高/中/低>"}
  ],
  "公告解读": "<近期公告的综合解读>",
  "市场情绪分析": "<当前市场对该股票的情绪描述>",
  "资金流向分析": "<资金流向情况分析>",
  "风险提示": ["<风险1>", "<风险2>", "<风险3>"],
  "催化剂": ["<潜在利好催化剂1>", "<潜在利好催化剂2>"],
  "近期关键新闻摘要": "<3-5条最重要新闻的简要汇总>",
  "综合结论": "<舆情面综合结论，100字以内>"
}
"""


def create_news_agent() -> ChatOpenAI:
    """
    创建新闻舆情分析 Agent

    Returns:
        绑定了工具的 ChatOpenAI 实例
    """
    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )

    tools = [get_stock_news]
    return llm.bind_tools(tools)


async def run_news_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行新闻舆情分析的完整流程

    Args:
        stock_code: 股票代码

    Returns:
        包含分析结果的字典
    """
    # 1. 获取新闻数据
    news_data = get_stock_news.invoke({"stock_code": stock_code})

    # 2. 构建分析提示
    user_message = f"""
请分析以下 A股 股票 {stock_code} 的新闻舆情：

**新闻及公告数据：**
{news_data}

请根据以上数据，按照系统提示的格式进行全面的舆情分析：
1. 识别并解读近期重大事件和公告
2. 判断市场对该股票的情绪倾向
3. 分析资金流向透露的主力意图
4. 提出明确的风险警示
5. 给出舆情面评分

注意：对于已明确的负面新闻（如监管处罚、大幅减持等）要给予足够的负面权重。
"""

    # 3. 调用 LLM 分析
    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )

    messages = [
        SystemMessage(content=NEWS_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    # 4. 解析 JSON 结果
    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            analysis_result = {"raw_analysis": analysis_text, "情绪评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "情绪评分": 50}

    return {
        "agent": "news_agent",
        "stock_code": stock_code,
        "raw_data": {
            "news_data": news_data,
        },
        "analysis": analysis_result,
        "score": analysis_result.get("情绪评分", 50),
    }
