"""
供需分析 Agent（条件四）
分析产品涨价逻辑和供需不平衡状态
这是选股最核心的驱动力之一：产品价格上涨 + 供不应求 = 业绩超预期
输出供需评分（0-100）
"""

import json
import re
from typing import Any

import akshare as ak
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings
from tools.news_tools import get_stock_news
from tools.stock_data import get_stock_basic_info, get_financial_indicators


SUPPLY_DEMAND_SYSTEM_PROMPT = """你是一位专注于产业链和供需分析的专家，擅长判断产品价格走势和供需结构对上市公司的影响。

你的任务是分析该公司核心产品的供需状况，判断：
1. **产品价格趋势**：核心产品价格是否在上涨或有上涨预期
2. **供给端分析**：产能是否受限（环保/资质/资源稀缺性）
3. **需求端分析**：下游需求是否在持续扩张
4. **供需缺口**：是否存在明显的供不应求
5. **涨价持续性**：涨价是否具有可持续性（非短期投机）

评分标准（满分100分，基准50分）：
- 产品已在明显涨价+供不应求确立：+35分
- 供给受限有长期逻辑（资质/资源壁垒）：+20分
- 下游需求持续扩张：+15分
- 产品价格平稳，供需平衡：0分（维持50）
- 产品价格下跌/产能过剩：-20至-40分

加分项：
- 涨价已传导至业绩（利润增速加快）：+10分
- 竞争格局改善（行业整合）：+10分

请以结构化的JSON格式输出：
{
  "供需评分": <0-100的整数>,
  "供需状态": "<严重供不应求/供不应求/供需平衡/供大于求/严重过剩>",
  "核心产品": "<公司主要产品名称>",
  "价格趋势": "<明显上涨/温和上涨/平稳/温和下跌/明显下跌>",
  "供给端分析": "<产能/供给限制情况>",
  "需求端分析": "<下游需求情况>",
  "供需缺口预测": "<未来6-12个月的供需预测>",
  "涨价催化剂": ["<催化剂1>", "<催化剂2>"],
  "主要风险": ["<风险1：如需求下滑>", "<风险2：如新增产能>"],
  "综合结论": "<50字以内总结>"
}
"""


def _get_commodity_price_data(stock_code: str, industry: str = "") -> str:
    """
    尝试获取相关商品价格数据
    基于行业尝试获取对应大宗商品价格
    """
    price_data = {"获取时间": "当前", "说明": "基于行业特征获取相关大宗商品或期货价格"}

    try:
        # 尝试获取部分商品价格作为参考
        # 钢铁/有色金属行业
        if any(kw in industry for kw in ["钢铁", "有色", "铝", "铜", "锂", "钴", "镍"]):
            try:
                spot_df = ak.spot_hist_sge(symbol="Au99.95")  # 黄金现货作为代表
                if spot_df is not None and not spot_df.empty:
                    price_data["贵金属现货参考"] = spot_df.tail(5).to_dict(orient="records")
            except Exception:
                pass

        # 化工行业
        if any(kw in industry for kw in ["化工", "塑料", "橡胶", "聚酯"]):
            price_data["建议参考"] = "化工品期货价格（PTA、乙烯、聚丙烯等）"

        # 煤炭/能源
        if any(kw in industry for kw in ["煤炭", "能源", "焦煤", "动力煤"]):
            price_data["建议参考"] = "煤炭期货价格"

    except Exception as e:
        price_data["价格数据获取备注"] = str(e)

    return json.dumps(price_data, ensure_ascii=False, indent=2, default=str)


async def run_supply_demand_analysis(stock_code: str) -> dict[str, Any]:
    """
    执行供需和涨价分析

    Args:
        stock_code: 股票代码

    Returns:
        包含供需分析结果的字典
    """
    # 获取数据
    basic_info = get_stock_basic_info.invoke({"stock_code": stock_code})
    financial_data = get_financial_indicators.invoke({"stock_code": stock_code})
    news_data = get_stock_news.invoke({"stock_code": stock_code})

    # 尝试从basic_info中提取行业信息
    industry = ""
    try:
        info_dict = json.loads(basic_info)
        industry = info_dict.get("行业", info_dict.get("所属行业", ""))
    except Exception:
        pass

    commodity_data = _get_commodity_price_data(stock_code, industry)

    user_message = f"""
请分析 A股 股票 {stock_code} 的产品供需状况和涨价逻辑：

**公司基本信息（了解主营业务）：**
{basic_info}

**财务数据（判断涨价是否已传导至业绩）：**
{financial_data}

**近期相关新闻（判断供需动态）：**
{news_data}

**商品价格参考数据：**
{commodity_data}

请重点分析：
1. 该公司的核心产品/服务是什么，其价格近期是否在上涨
2. 供给端有哪些约束（资质壁垒、原材料稀缺、环保限产等）
3. 下游需求是否在扩张（新能源、国产替代、出口增加等）
4. 供需缺口预计能持续多久
5. 涨价逻辑是否已体现在业绩改善中（从财务数据判断）

核心判断：是否符合"产品涨价+供需不平衡"的选股条件？
"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )

    messages = [
        SystemMessage(content=SUPPLY_DEMAND_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            analysis_result = {"raw_analysis": analysis_text, "供需评分": 50}
    except json.JSONDecodeError:
        analysis_result = {"raw_analysis": analysis_text, "供需评分": 50}

    return {
        "agent": "supply_demand_agent",
        "stock_code": stock_code,
        "raw_data": {
            "basic_info": basic_info,
            "financial_data": financial_data,
        },
        "analysis": analysis_result,
        "score": analysis_result.get("供需评分", 50),
    }
