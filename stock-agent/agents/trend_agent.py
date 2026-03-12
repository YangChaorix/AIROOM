"""
中长期趋势 Agent（条件五）
分析股票未来半年~2年的上涨趋势
综合基本面趋势（业绩成长性）和中长期K线走势
输出趋势评分（0-100）
"""

import json
import re
from typing import Any
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.stock_data import get_financial_indicators, get_historical_kline


TREND_SYSTEM_PROMPT = """你是一位专注于中长期价值投资趋势分析的专家，专门判断股票未来6个月至2年的上涨概率。

你的任务是综合基本面成长趋势和中长期技术走势，评估未来6个月到2年的上涨潜力。

分析维度：
1. **业绩成长趋势**：营收/净利润是否持续增长（连续3年以上成长更可靠）
2. **估值合理性**：当前估值是否处于历史低位或合理区间（PE/PB的历史分位数）
3. **中长期技术走势**：月线/季线是否多头排列
4. **行业景气度周期**：行业是否处于上升周期的初/中期
5. **基本面改善趋势**：ROE改善、毛利率提升、现金流改善

评分标准（满分100分）：
- 业绩连续3年+增长，且增速在加快：+30分
- 估值处于历史低位（20%分位以下）：+20分
- 中长期均线多头排列（月线级别）：+20分
- 行业处于景气上升周期初中期：+15分
- ROE持续改善（>15%）：+15分
- 业绩停滞或下滑：-30分
- 估值历史高位：-20分
- 技术上长期下跌趋势：-20分

请以结构化的JSON格式输出：
{
  "趋势评分": <0-100的整数>,
  "趋势判断": "<强势上涨趋势/温和上升趋势/震荡趋势/温和下降趋势/下跌趋势>",
  "业绩成长分析": "<近3年业绩增长趋势分析>",
  "估值分析": "<当前估值是否合理，历史分位数>",
  "中长期技术分析": "<月线/季线趋势分析>",
  "行业景气度": "<行业周期位置判断>",
  "预期上涨空间(%)": <未来12个月预期涨幅估算>,
  "主要驱动因素": ["<驱动力1>", "<驱动力2>"],
  "主要下行风险": ["<风险1>", "<风险2>"],
  "投资时间框架": "<推荐持有周期>",
  "综合结论": "<50字以内总结>"
}
"""


def _get_long_term_kline(stock_code: str) -> str:
    """获取长期K线数据（近2年）用于趋势分析"""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=730)  # 2年

        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="weekly",  # 使用周线
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq",
        )

        if df is None or df.empty:
            return json.dumps({"error": "无法获取长期K线数据"}, ensure_ascii=False)

        col_map = {
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "涨跌幅": "pct_change",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df = df.sort_values("date").reset_index(drop=True)

        if "close" not in df.columns:
            return json.dumps({"error": "K线数据格式异常"}, ensure_ascii=False)

        close = df["close"].astype(float)

        # 计算长期均线
        ma26 = round(float(close.rolling(26).mean().iloc[-1]), 3) if len(close) >= 26 else None
        ma52 = round(float(close.rolling(52).mean().iloc[-1]), 3) if len(close) >= 52 else None
        ma104 = round(float(close.rolling(104).mean().iloc[-1]), 3) if len(close) >= 104 else None

        current_price = round(float(close.iloc[-1]), 3)
        price_52w_high = round(float(close.tail(52).max()), 3)
        price_52w_low = round(float(close.tail(52).min()), 3)

        # 计算2年涨跌幅
        pct_2y = round((close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100, 2) if len(close) > 1 else 0

        # 判断长期趋势
        if ma26 and ma52:
            if current_price > ma26 > ma52:
                long_trend = "长期上升趋势（价格在长期均线上方且均线多头）"
            elif current_price < ma26 < ma52:
                long_trend = "长期下降趋势（价格在长期均线下方且均线空头）"
            else:
                long_trend = "长期震荡趋势（均线交叉或价格在均线附近）"
        else:
            long_trend = "数据不足，无法判断长期趋势"

        result = {
            "当前价格": current_price,
            "52周最高": price_52w_high,
            "52周最低": price_52w_low,
            "距52周高点(%)": round((current_price - price_52w_high) / price_52w_high * 100, 2),
            "距52周低点(%)": round((current_price - price_52w_low) / price_52w_low * 100, 2),
            "2年涨跌幅(%)": pct_2y,
            "26周均线(MA26)": ma26,
            "52周均线(MA52)": ma52,
            "104周均线(MA104)": ma104,
            "长期趋势判断": long_trend,
            "近20周K线(取样)": df.tail(20)[["date", "close", "volume"]].to_dict(orient="records") if "date" in df.columns else [],
        }

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": f"获取长期K线失败: {str(e)}"
        }, ensure_ascii=False)


async def run_trend_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行中长期趋势分析

    Args:
        stock_code: 股票代码

    Returns:
        包含趋势分析结果的字典
    """
    # 获取数据
    financial_data = get_financial_indicators.invoke({"stock_code": stock_code})
    long_term_kline = _get_long_term_kline(stock_code)

    user_message = f"""
请分析 A股 股票 {stock_code} 未来6个月至2年的中长期上涨趋势：

**财务指标数据（判断基本面成长趋势）：**
{financial_data}

**中长期K线数据（周线级别）：**
{long_term_kline}

请重点评估：
1. **业绩成长性**：近3年营收和净利润增速是否稳定向上？增速是否在加快？
2. **估值合理性**：PE/PB是否处于历史合理或低估区间？
3. **中长期技术趋势**：月线/周线级别是否处于上升通道？关键支撑是否稳固？
4. **行业景气度**：行业整体是否处于景气周期的初期或中期？
5. **ROE趋势**：净资产收益率是否持续在提升？

核心判断：这只股票未来6个月~2年是否具备持续上涨的基础？
"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )

    messages = [
        SystemMessage(content=TREND_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            analysis_result = {"raw_analysis": analysis_text, "趋势评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "趋势评分": 50}

    return {
        "agent": "trend_agent",
        "stock_code": stock_code,
        "raw_data": {
            "financial_data": financial_data,
            "long_term_kline": long_term_kline,
        },
        "analysis": analysis_result,
        "score": analysis_result.get("趋势评分", 50),
    }
