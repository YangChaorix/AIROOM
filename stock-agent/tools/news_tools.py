"""
新闻与舆情工具模块
使用 akshare 获取股票相关新闻、公告、舆情数据
封装为 LangChain Tool 供 Agent 使用
"""

import json
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import akshare as ak
import pandas as pd
from langchain_core.tools import tool

from config.settings import settings


def _truncate_text(text: str, max_length: int = 200) -> str:
    """截断过长文本，保留关键信息"""
    if not text or not isinstance(text, str):
        return ""
    text = text.strip().replace("\n", " ").replace("\r", "")
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


def _parse_date_str(date_str: str) -> Optional[str]:
    """解析各种格式的日期字符串，返回标准格式"""
    if not date_str:
        return None
    try:
        # 尝试多种格式
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
            try:
                dt = datetime.strptime(str(date_str)[:19], fmt[:len(str(date_str)[:19])])
                return dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
        return str(date_str)
    except Exception:
        return str(date_str)


@tool
def get_stock_news(stock_code: str) -> str:
    """
    获取股票相关新闻资讯和公司公告，用于分析市场舆情和重大事件。

    Args:
        stock_code: A股股票代码，如 '000001' 或 '600519'

    Returns:
        JSON格式的新闻和公告数据字符串，包含标题、摘要、时间等信息
    """
    result = {
        "股票代码": stock_code,
        "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "新闻资讯": [],
        "公司公告": [],
        "市场情绪": {},
    }

    # 1. 获取东方财富股票新闻
    try:
        news_df = ak.stock_news_em(symbol=stock_code)
        if news_df is not None and not news_df.empty:
            news_count = min(settings.akshare.news_count, len(news_df))
            news_list = []
            for _, row in news_df.head(news_count).iterrows():
                news_item = {
                    "标题": _truncate_text(str(row.get("新闻标题", row.get("title", ""))), 100),
                    "内容摘要": _truncate_text(str(row.get("新闻内容", row.get("content", ""))), 200),
                    "发布时间": _parse_date_str(str(row.get("发布时间", row.get("datetime", "")))),
                    "来源": str(row.get("文章来源", row.get("source", "东方财富"))),
                }
                # 过滤空标题
                if news_item["标题"] and news_item["标题"] != "nan":
                    news_list.append(news_item)
            result["新闻资讯"] = news_list
    except Exception as e:
        result["新闻获取错误"] = f"东方财富新闻获取失败: {str(e)}"

    # 2. 获取股票公告
    try:
        # 获取最近30天的公告
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

        notice_df = ak.stock_notice_report(symbol=stock_code, date=end_date)
        if notice_df is not None and not notice_df.empty:
            notices = []
            for _, row in notice_df.head(10).iterrows():
                notice = {
                    "标题": _truncate_text(str(row.get("公告标题", row.get("title", ""))), 100),
                    "公告类型": str(row.get("公告类型", row.get("type", ""))),
                    "发布日期": _parse_date_str(str(row.get("公告日期", row.get("date", "")))),
                }
                if notice["标题"] and notice["标题"] != "nan":
                    notices.append(notice)
            result["公司公告"] = notices
    except Exception as e:
        result["公告获取备注"] = f"公告获取失败（可能无数据）: {str(e)}"

    # 3. 获取个股资金流向（反映市场关注度）
    try:
        fund_flow_df = ak.stock_individual_fund_flow(
            stock=stock_code, market="sh" if stock_code.startswith("6") else "sz"
        )
        if fund_flow_df is not None and not fund_flow_df.empty:
            recent = fund_flow_df.tail(5)
            fund_data = []
            for _, row in recent.iterrows():
                record = {}
                for col in recent.columns:
                    val = row[col]
                    record[col] = str(val) if not (isinstance(val, float) and pd.isna(val)) else "N/A"
                fund_data.append(record)
            result["近5日资金流向"] = fund_data
    except Exception as e:
        result["资金流向备注"] = f"资金流向获取失败: {str(e)}"

    # 4. 获取龙虎榜数据（如果有）
    try:
        today = datetime.now().strftime("%Y%m%d")
        lhb_df = ak.stock_lhb_detail_em(start_date=today, end_date=today)
        if lhb_df is not None and not lhb_df.empty:
            # 筛选指定股票
            stock_lhb = lhb_df[lhb_df["代码"] == stock_code]
            if not stock_lhb.empty:
                result["今日龙虎榜"] = stock_lhb.to_dict(orient="records")
    except Exception:
        pass  # 龙虎榜数据可选，失败不影响主流程

    # 5. 情绪分析摘要
    news_count = len(result.get("新闻资讯", []))
    notice_count = len(result.get("公司公告", []))

    # 简单的关键词情绪分析
    positive_keywords = ["增长", "利好", "突破", "创新高", "超预期", "战略", "合作", "中标", "获得", "扩张", "盈利"]
    negative_keywords = ["下滑", "亏损", "减持", "风险", "调查", "处罚", "违规", "诉讼", "下调", "警示", "退市"]

    positive_count = 0
    negative_count = 0

    all_titles = [n.get("标题", "") for n in result.get("新闻资讯", [])]
    all_titles += [n.get("标题", "") for n in result.get("公司公告", [])]

    for title in all_titles:
        for kw in positive_keywords:
            if kw in title:
                positive_count += 1
                break
        for kw in negative_keywords:
            if kw in title:
                negative_count += 1
                break

    if positive_count > negative_count * 1.5:
        sentiment = "偏正面"
    elif negative_count > positive_count * 1.5:
        sentiment = "偏负面"
    else:
        sentiment = "中性"

    result["市场情绪"] = {
        "新闻条数": news_count,
        "公告条数": notice_count,
        "正面信号数": positive_count,
        "负面信号数": negative_count,
        "综合情绪": sentiment,
        "分析说明": f"基于{news_count}条新闻和{notice_count}条公告的关键词情绪分析",
    }

    return json.dumps(result, ensure_ascii=False, indent=2, default=str)
