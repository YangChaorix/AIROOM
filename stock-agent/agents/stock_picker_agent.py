"""
LLM 轻量预筛选 Agent

单次 LLM 调用，从 Python 初筛后的候选股票中选出最值得深入分析的 Top N。
输入尽量精简以降低 token 消耗。
"""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings


PICKER_SYSTEM_PROMPT = """你是一位A股选股专家，负责从候选股票中筛选出最值得深入研究的标的。

筛选标准（按优先级）：
1. 与今日政策/新闻高度相关的行业龙头或细分赛道标的
2. 基本面有支撑，非纯游资短线炒作
3. 有中长期逻辑，不只是当日热点

输出格式（严格JSON，不要其他内容）：
{
  "top_stocks": ["600519", "300750", ...],
  "reasoning": "简要说明选股逻辑（100字以内）"
}"""


async def run_stock_picker(
    candidates: list[dict[str, Any]],
    news_summary: str,
    top_n: int = 10,
) -> list[str]:
    """
    LLM轻量预筛，返回最值得深入分析的股票代码列表

    Args:
        candidates: Python初筛后的候选股票（含行业、涨幅、新闻匹配分）
        news_summary: 今日新闻标题摘要
        top_n: 最终保留数量

    Returns:
        股票代码列表
    """
    if not candidates:
        return []

    # 构造紧凑的候选股票表格（减少token）
    stock_lines = []
    for s in candidates[:30]:  # 最多传入30只，避免context过长
        hits = "/".join(s.get("命中新闻", [])) or "无"
        stock_lines.append(
            f"{s['代码']} {s['名称']} | 行业:{s.get('行业','?')} | "
            f"涨幅:{s['涨跌幅']}% | 市值:{s.get('流通市值(亿)',0)}亿 | 新闻命中:{hits}"
        )

    user_message = f"""今日新闻要点：
{news_summary}

候选股票（Python初筛后，按综合分排序）：
{chr(10).join(stock_lines)}

请从以上候选股票中选出最值得深入分析的Top{top_n}只。
要求：优先选与今日新闻政策相关、有基本面支撑的标的，排除纯炒作概念股。
输出JSON格式。"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=0.1,
        max_tokens=512,  # 输出精简，节省token
    )

    messages = [
        SystemMessage(content=PICKER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    text = response.content

    try:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            result = json.loads(match.group())
            codes = result.get("top_stocks", [])
            reasoning = result.get("reasoning", "")
            print(f"[AI预筛] 选出 {len(codes)} 只：{codes}")
            print(f"[AI预筛] 理由：{reasoning}")
            # 校验代码格式（6位数字）
            valid = [c for c in codes if str(c).isdigit() and len(str(c)) == 6]
            return valid[:top_n]
    except (json.JSONDecodeError, Exception):
        pass

    # 解析失败时兜底：直接取初筛分最高的top_n
    print("[AI预筛] 解析失败，使用初筛分兜底")
    return [s["代码"] for s in candidates[:top_n]]
