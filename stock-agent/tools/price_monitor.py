"""
C4 涨价检测工具（纯 Python，0 LLM token）

通过 akshare 期货历史价格检测商品近3个月涨幅是否 ≥20%，
用于 Agent 1 的 C4（供需涨价）条件判断。
"""

from datetime import datetime, timedelta
from typing import Any

import akshare as ak
import pandas as pd


# 行业 → 期货合约代码映射（新浪主力合约格式）
COMMODITY_FUTURES_MAP: dict[str, list[str]] = {
    "煤炭":   ["ZC0"],
    "钢铁":   ["RB0"],
    "有色金属": ["CU0", "AL0"],
    "化工":   ["TA0"],
    "石油":   ["SC0"],
    "农业":   ["C0", "M0"],
    "电池":   [],  # 碳酸锂无主力期货，由新闻关键词替代
}

# C4 触发阈值：近3个月涨幅超过此值视为满足条件
C4_THRESHOLD_PCT = 20.0


def get_commodity_price_change(industry: str) -> dict[str, Any]:
    """
    获取指定行业的商品期货近3个月价格涨幅

    Args:
        industry: 行业名称，需在 COMMODITY_FUTURES_MAP 中定义

    Returns:
        {
            "industry": str,
            "symbols": list[str],
            "max_pct_change_3m": float | None,
            "meets_c4": bool,
            "detail": list[dict],  # 每个合约的涨幅明细
            "error": str | None,
        }
    """
    symbols = COMMODITY_FUTURES_MAP.get(industry, [])
    if not symbols:
        return {
            "industry": industry,
            "symbols": [],
            "max_pct_change_3m": None,
            "meets_c4": False,
            "detail": [],
            "error": "无对应期货合约（需用新闻关键词替代）",
        }

    detail = []
    max_pct = None

    for symbol in symbols:
        try:
            df = ak.futures_main_sina(symbol=symbol, start_date="20200101")
            if df is None or df.empty:
                detail.append({"symbol": symbol, "error": "无数据"})
                continue

            # 统一列名
            col_map = {"date": "date", "close": "close", "settlement": "close"}
            # akshare futures_main_sina 返回列：date, open, high, low, close, volume, hold, ...
            if "date" not in df.columns:
                # 尝试第一列为日期
                df = df.rename(columns={df.columns[0]: "date"})
            if "close" not in df.columns and "收盘价" in df.columns:
                df = df.rename(columns={"收盘价": "close"})
            if "close" not in df.columns:
                # 取第5列作为收盘价（通常为close/settlement）
                df = df.rename(columns={df.columns[4]: "close"})

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])

            if len(df) < 2:
                detail.append({"symbol": symbol, "error": "数据量不足"})
                continue

            # 近3个月：约63个交易日
            cutoff_date = datetime.now() - timedelta(days=90)
            recent = df[df["date"] >= cutoff_date]

            if len(recent) < 2:
                # 回退到最后63条数据
                recent = df.tail(63)

            start_price = float(recent["close"].iloc[0])
            end_price = float(recent["close"].iloc[-1])

            if start_price <= 0:
                detail.append({"symbol": symbol, "error": "起始价格异常"})
                continue

            pct_change = round((end_price - start_price) / start_price * 100, 2)

            detail.append({
                "symbol": symbol,
                "start_price": start_price,
                "end_price": end_price,
                "pct_change_3m": pct_change,
                "start_date": recent["date"].iloc[0].strftime("%Y-%m-%d"),
                "end_date": recent["date"].iloc[-1].strftime("%Y-%m-%d"),
            })

            if max_pct is None or pct_change > max_pct:
                max_pct = pct_change

        except Exception as e:
            detail.append({"symbol": symbol, "error": str(e)})

    meets_c4 = max_pct is not None and max_pct >= C4_THRESHOLD_PCT

    return {
        "industry": industry,
        "symbols": symbols,
        "max_pct_change_3m": max_pct,
        "meets_c4": meets_c4,
        "detail": detail,
        "error": None,
    }


def scan_all_industry_prices() -> list[dict[str, Any]]:
    """
    扫描所有有期货合约的行业，返回满足 C4 条件（近3个月涨幅≥20%）的行业列表

    Returns:
        满足 C4 的行业数据列表，每项为 get_commodity_price_change 的返回值
    """
    triggered = []
    for industry in COMMODITY_FUTURES_MAP:
        result = get_commodity_price_change(industry)
        if result["meets_c4"]:
            triggered.append(result)
    return triggered
