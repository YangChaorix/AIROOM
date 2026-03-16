"""
政策分析 Agent（条件一）
分析是否有新政策支持该股票所在行业
输出政策评分（0-100）和政策分析报告
"""

import json
import re
from datetime import datetime, timedelta
from typing import Any

import akshare as ak
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
    # 1. 个股新闻和公告
    news_data = get_stock_news.invoke({"stock_code": stock_code})

    # 2. 同花顺全球财经快讯（宏观政策信号）
    global_news_text = ""
    try:
        df = ak.stock_info_global_ths()
        if df is not None and not df.empty:
            items = []
            for _, row in df.head(15).iterrows():
                items.append(f"[{row.get('发布时间', '')}] {row.get('标题', '')}\n{str(row.get('内容', ''))[:200]}")
            global_news_text = "\n\n".join(items)
    except Exception:
        global_news_text = "获取失败"

    # 3. 央视新闻联播（国家政策权威来源，当天播出前无数据，往前最多找3天）
    cctv_text = ""
    try:
        for delta in range(3):
            date_str = (datetime.now() - timedelta(days=delta)).strftime("%Y%m%d")
            df = ak.news_cctv(date=date_str)
            if df is not None and not df.empty:
                items = []
                for _, row in df.iterrows():
                    items.append(f"【{row.get('title', '')}】\n{str(row.get('content', ''))[:300]}")
                cctv_text = f"（来源：{date_str} 新闻联播）\n\n" + "\n\n".join(items)
                break
    except Exception:
        cctv_text = "获取失败"

    user_message = f"""
请分析 A股 股票 {stock_code} 所在行业的政策面情况：

**一、个股近期新闻和公告：**
{news_data}

**二、同花顺全球财经快讯（宏观政策信号）：**
{global_news_text}

**三、央视新闻联播（国家政策权威来源）：**
{cctv_text}

请综合以上三类信息，重点关注：
1. 央视/政府文件中是否有涉及该行业的政策方向（五年规划、产业政策、监管动向）
2. 全球财经快讯中是否有影响该行业的宏观政策（财政、货币、产业补贴等）
3. 个股新闻中是否有具体政策利好/利空
4. 行业监管环境整体是否友好

注意：如果信息中政策信号不足，请基于行业基本情况给出合理判断并说明依据。
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
        "raw_data": {"news_data": news_data, "global_news": global_news_text, "cctv_news": cctv_text},
        "analysis": analysis_result,
        "score": analysis_result.get("政策评分", 50),
    }
