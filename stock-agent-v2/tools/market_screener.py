"""
市场行情工具：涨跌幅榜，供 review_agent 复盘使用
"""

from datetime import datetime
from typing import Any

import akshare as ak
import pandas as pd


def get_market_movers(top_n: int = 50) -> dict[str, Any]:
    """
    获取当日A股涨幅前N名和跌幅前N名
    返回用于复盘分析的数据
    """
    result = {
        "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "涨幅前50": [],
        "跌幅前50": [],
        "市场概况": {},
    }

    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            result["error"] = "无法获取行情数据"
            return result

        df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
        df = df.dropna(subset=["涨跌幅"])

        # 过滤 ST
        df = df[~df["名称"].str.contains("ST|退", na=False)]

        # 涨幅前N
        gainers = df.nlargest(top_n, "涨跌幅")
        for _, row in gainers.iterrows():
            result["涨幅前50"].append({
                "代码": str(row.get("代码", "")).zfill(6),
                "名称": str(row.get("名称", "")),
                "最新价": float(row.get("最新价", 0) or 0),
                "涨跌幅(%)": float(row.get("涨跌幅", 0) or 0),
                "换手率(%)": float(row.get("换手率", 0) or 0),
                "成交额(亿)": round(float(row.get("成交额", 0) or 0) / 1e8, 2),
            })

        # 跌幅前N
        losers = df.nsmallest(top_n, "涨跌幅")
        for _, row in losers.iterrows():
            result["跌幅前50"].append({
                "代码": str(row.get("代码", "")).zfill(6),
                "名称": str(row.get("名称", "")),
                "最新价": float(row.get("最新价", 0) or 0),
                "涨跌幅(%)": float(row.get("涨跌幅", 0) or 0),
                "换手率(%)": float(row.get("换手率", 0) or 0),
            })

        # 市场概况
        avg_pct = float(df["涨跌幅"].mean())
        up_count = int((df["涨跌幅"] > 0).sum())
        down_count = int((df["涨跌幅"] < 0).sum())
        result["市场概况"] = {
            "上涨家数": up_count,
            "下跌家数": down_count,
            "平均涨跌幅(%)": round(avg_pct, 2),
            "市场情绪": "偏强" if avg_pct > 0.3 else ("偏弱" if avg_pct < -0.3 else "中性"),
        }

    except Exception as e:
        result["error"] = str(e)

    return result


def get_sector_performance() -> list[dict]:
    """
    获取板块涨跌幅（行业板块）
    """
    try:
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.iterrows():
            result.append({
                "板块名称": str(row.get("板块名称", "")),
                "涨跌幅(%)": float(row.get("涨跌幅", 0) or 0),
                "涨跌额": float(row.get("涨跌额", 0) or 0),
                "总市值(亿)": round(float(row.get("总市值", 0) or 0) / 1e8, 2),
            })
        result.sort(key=lambda x: x["涨跌幅(%)"], reverse=True)
        return result
    except Exception:
        return []
