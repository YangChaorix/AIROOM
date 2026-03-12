"""
技术面分析 Agent
分析股票技术指标：趋势、动量、支撑压力位等
输出技术面评分（0-100）和详细分析报告
"""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.stock_data import get_historical_kline
from tools.technical_indicators import calculate_technical_indicators


# 技术面分析的系统提示词
TECHNICAL_SYSTEM_PROMPT = """你是一位专业的A股技术分析师，擅长通过图表和技术指标判断股票走势。

你的任务是分析股票的技术面数据，包括：
1. **趋势分析**：均线排列（多头/空头/震荡）、趋势方向和强度
2. **动量指标**：MACD（金叉/死叉）、RSI（超买/超卖）、KDJ状态
3. **波动性分析**：布林带位置、带宽收窄/扩张
4. **成交量分析**：量价关系、成交量趋势
5. **支撑压力位**：关键支撑位和压力位识别

评分标准（满分100分）：
- 趋势强度（25分）：均线多头排列+25，空头-排列+0，震荡+12
- MACD状态（20分）：金叉+上涨区+20，其他情况按强度给分
- RSI状态（15分）：正常区间+15，超买/超卖适当扣分
- 布林带位置（15分）：位于中轨以上偏好
- 量价配合（15分）：量增价涨或量缩价稳为正面信号
- 支撑压力（10分）：距离支撑位近、距离压力位远为正面

请以结构化的JSON格式输出分析结果，格式如下：
{
  "技术面评分": <0-100的整数>,
  "评分等级": "<强势/偏强/中性/偏弱/弱势>",
  "趋势分析": "<均线趋势详细分析>",
  "MACD分析": "<MACD指标分析>",
  "RSI分析": "<RSI超买超卖分析>",
  "布林带分析": "<布林带位置和信号分析>",
  "KDJ分析": "<KDJ随机指标分析>",
  "量价分析": "<成交量与价格关系分析>",
  "支撑压力分析": "<关键价位分析>",
  "核心看多信号": ["<信号1>", "<信号2>"],
  "核心看空信号": ["<信号1>", "<信号2>"],
  "短期展望": "<未来1-2周的技术面展望>",
  "建议操作": "<积极做多/谨慎做多/观望/谨慎做空/回避>"
}
"""


def create_technical_agent() -> ChatOpenAI:
    """
    创建技术面分析 Agent

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

    tools = [get_historical_kline, calculate_technical_indicators]
    return llm.bind_tools(tools)


async def run_technical_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行技术面分析的完整流程

    Args:
        stock_code: 股票代码

    Returns:
        包含分析结果的字典
    """
    # 1. 获取技术指标数据
    technical_data = calculate_technical_indicators.invoke({"stock_code": stock_code})
    kline_data = get_historical_kline.invoke({"stock_code": stock_code})

    # 2. 构建分析提示
    user_message = f"""
请分析以下 A股 股票 {stock_code} 的技术面：

**技术指标数据：**
{technical_data}

**历史K线统计：**
{kline_data}

请根据以上技术数据，按照系统提示的格式进行全面的技术面分析，给出评分并判断当前是否适合介入。
重点关注：
1. 当前趋势是否明确
2. 主要技术指标是否共振（多个指标方向一致）
3. 量价是否配合
4. 关键支撑压力位置
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
        SystemMessage(content=TECHNICAL_SYSTEM_PROMPT),
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
            analysis_result = {"raw_analysis": analysis_text, "技术面评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "技术面评分": 50}

    return {
        "agent": "technical_agent",
        "stock_code": stock_code,
        "raw_data": {
            "technical_indicators": technical_data,
            "kline_stats": kline_data,
        },
        "analysis": analysis_result,
        "score": analysis_result.get("技术面评分", 50),
    }
