"""
新闻采集工具：获取发改委/财联社/新华社/同花顺等来源的新闻
供 trigger_agent 使用
"""

import json
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd

from config.settings import settings


def _truncate(text: str, max_len: int = 300) -> str:
    if not text or not isinstance(text, str):
        return ""
    text = text.strip().replace("\n", " ").replace("\r", "")
    return text[:max_len] + "..." if len(text) > max_len else text


def _parse_date(date_str: str) -> Optional[str]:
    if not date_str:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
        try:
            dt = datetime.strptime(str(date_str)[:len(fmt)], fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return str(date_str)


def get_today_macro_news() -> list[dict]:
    """
    获取今日宏观政策新闻（财联社宏观）
    返回新闻列表，供 trigger_agent 分析触发条件
    """
    news_list = []
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. 财联社快讯
    try:
        df = ak.stock_telegraph_cls()
        if df is not None and not df.empty:
            for _, row in df.head(settings.akshare.news_count).iterrows():
                item = {
                    "标题": _truncate(str(row.get("内容", row.get("title", ""))), 200),
                    "来源": "财联社",
                    "时间": _parse_date(str(row.get("时间", row.get("time", "")))),
                }
                if item["标题"] and item["标题"] != "nan":
                    news_list.append(item)
    except Exception as e:
        news_list.append({"来源": "财联社", "错误": str(e)})

    # 2. 东方财富宏观新闻
    try:
        df = ak.news_economic_baidu()
        if df is not None and not df.empty:
            for _, row in df.head(20).iterrows():
                item = {
                    "标题": _truncate(str(row.get("title", row.get("标题", ""))), 200),
                    "来源": "东方财富宏观",
                    "时间": _parse_date(str(row.get("date", row.get("时间", "")))),
                }
                if item["标题"] and item["标题"] != "nan":
                    news_list.append(item)
    except Exception as e:
        pass

    # 3. 同花顺快讯
    try:
        df = ak.stock_info_global_ths()
        if df is not None and not df.empty:
            for _, row in df.head(20).iterrows():
                item = {
                    "标题": _truncate(str(row.get("标题", row.get("title", ""))), 200),
                    "内容": _truncate(str(row.get("内容", row.get("content", ""))), 300),
                    "来源": "同花顺",
                    "时间": _parse_date(str(row.get("时间", row.get("time", "")))),
                }
                if item["标题"] and item["标题"] != "nan":
                    news_list.append(item)
    except Exception as e:
        pass

    return news_list


def get_policy_news() -> list[dict]:
    """
    获取财经政策新闻（专注于实质性政策）
    """
    news_list = []

    # 新华社/央行/发改委等财经资讯
    try:
        df = ak.stock_news_main_sina()
        if df is not None and not df.empty:
            for _, row in df.head(30).iterrows():
                item = {
                    "标题": _truncate(str(row.get("标题", row.get("title", ""))), 200),
                    "内容": _truncate(str(row.get("内容", row.get("content", ""))), 300),
                    "来源": str(row.get("来源", "新浪财经")),
                    "时间": _parse_date(str(row.get("时间", row.get("date", "")))),
                }
                if item["标题"] and item["标题"] != "nan":
                    news_list.append(item)
    except Exception as e:
        pass

    return news_list


def get_all_trigger_news() -> dict:
    """
    汇总所有触发Agent需要的新闻数据
    返回结构化字典供LLM分析
    """
    result = {
        "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "今日宏观政策新闻": get_today_macro_news(),
        "财经政策资讯": get_policy_news(),
    }
    return result
