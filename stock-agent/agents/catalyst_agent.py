"""
转折催化剂 Agent（条件六）
识别能触发股价从下跌/震荡转为上涨的关键催化事件
转折催化剂是判断介入时机的核心
输出催化剂评分（0-100）
"""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.news_tools import get_stock_news
from tools.stock_data import get_stock_basic_info


CATALYST_SYSTEM_PROMPT = """你是一位专注于A股事件驱动投资的专家，擅长识别能触发股价转折的催化事件。

你的任务是分析该股票是否存在明确的转折催化剂，判断：
1. **业绩催化剂**：业绩预告超预期、扭亏为盈、订单大幅增长
2. **资本运作催化剂**：重组并购、定增、股权激励、回购注销
3. **产品/技术催化剂**：新产品上市、技术突破、获得重要资质/认证
4. **市场份额催化剂**：竞争对手退出、大客户获取、重要合同中标
5. **管理层催化剂**：优秀管理层加入、股权激励绑定利益
6. **外部环境催化剂**：政策利好落地、行业供给侧改革、并购重组预期

催化剂强度评估：
- 高确定性催化剂（已公告、已落地）：强催化（+30至+40分）
- 中等确定性催化剂（明确预期）：中等催化（+15至+29分）
- 低确定性催化剂（可能性大）：弱催化（+5至+14分）
- 无明确催化剂：中性（50分基准）
- 负面催化剂（利空落地/风险暴露）：-20至-40分

评分标准（满分100分，基准50分）：
- 有明确高确定性催化剂：80-100分
- 有中等确定性催化剂：65-79分
- 存在弱催化剂：55-64分
- 无明确催化剂：45-54分
- 存在负面催化剂：0-44分

请以结构化的JSON格式输出：
{
  "催化剂评分": <0-100的整数>,
  "催化剂等级": "<强催化/中等催化/弱催化/无明确催化剂/负面催化>",
  "已确认催化剂": [
    {"事件": "<>", "时间": "<>", "影响": "<>", "确定性": "<高/中/低>"}
  ],
  "潜在催化剂": [
    {"事件": "<>", "预期时间": "<>", "触发条件": "<>"}
  ],
  "转折信号识别": "<目前是否出现转折信号及依据>",
  "负面催化剂风险": ["<负面事件1>", "<负面事件2>"],
  "最佳介入时机分析": "<基于催化剂时间线，何时介入风险收益比最优>",
  "综合结论": "<50字以内总结>"
}
"""


async def run_catalyst_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行催化剂分析

    Args:
        stock_code: 股票代码

    Returns:
        包含催化剂分析结果的字典
    """
    # 获取新闻公告和基本信息
    news_data = get_stock_news.invoke({"stock_code": stock_code})
    basic_info = get_stock_basic_info.invoke({"stock_code": stock_code})

    user_message = f"""
请分析 A股 股票 {stock_code} 是否存在能触发股价转折的催化剂事件：

**公司基本信息：**
{basic_info}

**近期新闻和公告（识别催化剂的主要来源）：**
{news_data}

请重点识别以下类型的催化剂：
1. **已确认的利好事件**（已公告，已落地）：
   - 业绩超预期/业绩预增公告
   - 重大合同签订/中标公告
   - 股权激励/回购方案公告
   - 重组并购公告

2. **高概率潜在催化剂**：
   - 即将发布的季报/年报业绩
   - 预期中的政策落地
   - 产品上市/项目投产计划

3. **转折信号**：
   - 连续下跌后的底部特征
   - 机构开始建仓的信号
   - 行业拐点信号

判断原则：转折催化剂越明确、确定性越高，介入的风险越小、收益越大。
"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )

    messages = [
        SystemMessage(content=CATALYST_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            analysis_result = {"raw_analysis": analysis_text, "催化剂评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "催化剂评分": 50}

    return {
        "agent": "catalyst_agent",
        "stock_code": stock_code,
        "raw_data": {
            "news_data": news_data,
            "basic_info": basic_info,
        },
        "analysis": analysis_result,
        "score": analysis_result.get("催化剂评分", 50),
    }
