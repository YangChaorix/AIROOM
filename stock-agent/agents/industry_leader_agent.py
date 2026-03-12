"""
行业龙头确认 Agent（条件二）
判断股票是否为所在行业的龙头企业（市值/营收/市场份额前三）
输出行业地位评分（0-100）
"""

import json
import re
from typing import Any

import akshare as ak
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.stock_data import get_stock_basic_info, get_financial_indicators


INDUSTRY_LEADER_SYSTEM_PROMPT = """你是一位专注于A股行业分析的专家，擅长判断企业在行业中的竞争地位。

你的任务是判断该股票是否为所在行业的龙头企业，评估维度：
1. **市值排名**：在同行业中总市值排名（前三为龙头）
2. **营收/利润规模**：营收/净利润是否处于行业前列
3. **市场份额**：是否具有显著市场份额优势
4. **品牌/技术壁垒**：是否具有核心竞争优势（品牌、专利、规模效应）
5. **机构认可度**：是否被机构广泛覆盖和推荐

评分标准（满分100分）：
- 行业绝对龙头（市值前1、市场份额30%+）：90-100分
- 行业第二梯队龙头（市值前3）：75-89分
- 行业中等规模企业（市值前10）：55-74分
- 行业中小企业：35-54分
- 行业尾部企业：0-34分

额外加分项：
- 具有不可替代的核心技术/专利：+5分
- 国内细分市场绝对领导者：+5分
- 有明确的国际化布局：+3分

请以结构化的JSON格式输出：
{
  "行业地位评分": <0-100的整数>,
  "行业地位": "<绝对龙头/强势龙头/行业前列/行业中游/行业末游>",
  "所属行业": "<行业名称>",
  "市值排名分析": "<在行业中的市值排名情况>",
  "核心竞争优势": ["<优势1>", "<优势2>"],
  "主要竞争对手": ["<竞争对手1>", "<竞争对手2>"],
  "龙头溢价判断": "<是否值得龙头溢价及理由>",
  "行业集中度分析": "<该行业集中度及公司所处位置>",
  "综合结论": "<50字以内总结>"
}
"""


def _get_industry_peers(stock_code: str) -> str:
    """获取同行业公司市值排名数据"""
    try:
        # 先获取股票所属行业
        info_df = ak.stock_individual_info_em(symbol=stock_code)
        industry = "未知"
        if info_df is not None and not info_df.empty:
            if "item" in info_df.columns and "value" in info_df.columns:
                for _, row in info_df.iterrows():
                    if str(row.get("item", "")) in ["行业", "所属行业", "板块"]:
                        industry = str(row.get("value", "未知"))
                        break

        # 获取行业成分股（用于市值对比）
        peers_info = {"目标股票代码": stock_code, "所属行业": industry}

        try:
            # 获取行业板块成分股
            board_df = ak.stock_board_industry_cons_em(symbol=industry)
            if board_df is not None and not board_df.empty:
                # 按总市值排序
                if "总市值" in board_df.columns:
                    board_df["总市值"] = pd.to_numeric(board_df["总市值"], errors="coerce")
                    board_df = board_df.sort_values("总市值", ascending=False)

                    # 找到目标股票的排名
                    rank = board_df[board_df["代码"] == stock_code].index.tolist()
                    actual_rank = board_df.index.get_loc(rank[0]) + 1 if rank else "未找到"

                    # 取前10名
                    top10 = board_df.head(10)[["代码", "名称", "最新价", "总市值"]].to_dict(orient="records")
                    peers_info["行业市值排名Top10"] = top10
                    peers_info["目标股票市值排名"] = actual_rank
                    peers_info["行业总公司数"] = len(board_df)
        except Exception as e:
            peers_info["行业数据获取备注"] = str(e)

        return json.dumps(peers_info, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        return json.dumps({"error": f"获取行业同行数据失败: {str(e)}"}, ensure_ascii=False)


async def run_industry_leader_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行行业龙头分析

    Args:
        stock_code: 股票代码

    Returns:
        包含行业地位分析结果的字典
    """
    # 获取基本信息和财务数据
    basic_info = get_stock_basic_info.invoke({"stock_code": stock_code})
    financial_data = get_financial_indicators.invoke({"stock_code": stock_code})
    industry_peers = _get_industry_peers(stock_code)

    user_message = f"""
请分析 A股 股票 {stock_code} 在所属行业中的竞争地位和龙头属性：

**股票基本信息：**
{basic_info}

**财务指标数据：**
{financial_data}

**行业同行市值排名数据：**
{industry_peers}

请重点评估：
1. 该公司在行业中的市值排名（排名越靠前，龙头属性越强）
2. 营收规模是否处于行业领先水平
3. 是否具有明显的品牌、技术或规模壁垒
4. 机构对其行业地位的认可程度

注意：龙头企业通常在行业下行时跌幅小、在上行时涨幅大，具有更强的抗跌性。
"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )

    messages = [
        SystemMessage(content=INDUSTRY_LEADER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            analysis_result = {"raw_analysis": analysis_text, "行业地位评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "行业地位评分": 50}

    return {
        "agent": "industry_leader_agent",
        "stock_code": stock_code,
        "raw_data": {
            "basic_info": basic_info,
            "industry_peers": industry_peers,
        },
        "analysis": analysis_result,
        "score": analysis_result.get("行业地位评分", 50),
    }
