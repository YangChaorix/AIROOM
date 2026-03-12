"""
基本面分析 Agent
分析股票的财务指标：PE、PB、ROE、营收增长、盈利能力等
输出基本面评分（0-100）和详细分析报告
"""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.stock_data import get_stock_basic_info, get_financial_indicators


# 基本面分析的系统提示词
FUNDAMENTAL_SYSTEM_PROMPT = """你是一位专业的A股基本面分析师，拥有丰富的财务分析经验。

你的任务是分析股票的基本面数据，包括：
1. **估值分析**：PE（市盈率）、PB（市净率）与行业平均水平对比
2. **盈利能力**：ROE（净资产收益率）、ROA（总资产回报率）、净利率、毛利率
3. **成长性**：营收增长率、净利润增长率的历史趋势
4. **财务健康**：资产负债率、流动比率、速动比率
5. **综合评估**：基于以上指标给出基本面综合评分

评分标准（满分100分）：
- 估值合理性（20分）：PE/PB是否在合理区间，是否被低估
- 盈利能力（30分）：ROE>15%得满分，ROE<5%得0分，线性插值
- 成长性（25分）：营收/利润增长稳定且正向
- 财务健康（15分）：负债率合理、现金流充裕
- 行业地位（10分）：龙头溢价、竞争优势

请以结构化的JSON格式输出分析结果，格式如下：
{
  "基本面评分": <0-100的整数>,
  "评分等级": "<优秀/良好/一般/较差>",
  "估值分析": "<详细分析>",
  "盈利能力分析": "<详细分析>",
  "成长性分析": "<详细分析>",
  "财务健康分析": "<详细分析>",
  "核心优势": ["<优势1>", "<优势2>"],
  "主要风险": ["<风险1>", "<风险2>"],
  "综合结论": "<100字以内的总结>",
  "建议": "<买入/观望/规避>"
}
"""


def create_fundamental_agent() -> ChatOpenAI:
    """
    创建基本面分析 Agent（使用 DeepSeek 模型）

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

    # 绑定工具
    tools = [get_stock_basic_info, get_financial_indicators]
    return llm.bind_tools(tools)


async def run_fundamental_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行基本面分析的完整流程

    Args:
        stock_code: 股票代码

    Returns:
        包含分析结果的字典
    """
    import json

    # 1. 先获取工具数据
    basic_info = get_stock_basic_info.invoke({"stock_code": stock_code})
    financial_data = get_financial_indicators.invoke({"stock_code": stock_code})

    # 2. 构建分析提示
    user_message = f"""
请分析以下 A股 股票 {stock_code} 的基本面：

**股票基本信息：**
{basic_info}

**财务指标数据：**
{financial_data}

请根据以上数据，按照系统提示的格式进行全面的基本面分析，并给出评分和投资建议。
注意：如果某些数据缺失，请基于现有数据进行分析，并说明数据缺失情况。
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
        SystemMessage(content=FUNDAMENTAL_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    # 4. 尝试解析 JSON 结果
    try:
        # 提取 JSON 部分（LLM 可能会在 JSON 前后加一些说明）
        import re
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            analysis_result = {"raw_analysis": analysis_text, "基本面评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "基本面评分": 50}

    return {
        "agent": "fundamental_agent",
        "stock_code": stock_code,
        "raw_data": {
            "basic_info": basic_info,
            "financial_data": financial_data,
        },
        "analysis": analysis_result,
        "score": analysis_result.get("基本面评分", 50),
    }
