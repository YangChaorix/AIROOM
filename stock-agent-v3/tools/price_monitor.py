"""
涨价检测工具（v1.1 升级）
通过 akshare 期货历史价格检测商品近3个月涨幅是否 ≥20%
v1.1: 扩展了 COMMODITY_FUTURES_MAP，有色金属拆分为铜/铝/锌/铅/镍，新增铁矿石、豆油、白银
      新增锂/稀土（无主力期货，用新闻替代）
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


# v1.1 扩展：有色金属拆分 + 新增铁矿石/豆油/白银/锌/铅/镍/锂/稀土
COMMODITY_FUTURES_MAP: dict[str, list[str]] = {
    "煤炭":   ["ZC0"],
    "钢铁":   ["RB0"],
    "铜":     ["CU0"],        # 原有色金属拆分
    "铝":     ["AL0"],        # 原有色金属拆分
    "锌":     ["ZN0"],        # 新增
    "铅":     ["PB0"],        # 新增
    "镍":     ["NI0"],        # 新增
    "化工":   ["TA0", "MA0", "PP0"],  # 新增 PP0
    "石油":   ["SC0"],
    "农业":   ["C0", "M0", "Y0"],     # 新增豆油 Y0
    "黄金":   ["AU0"],
    "白银":   ["AG0"],        # 新增
    "橡胶":   ["RU0"],
    "玻璃":   ["FG0"],
    "纯碱":   ["SA0"],
    "铁矿石": ["I0"],         # 新增
    "锂":     [],             # 碳酸锂无主力期货，由新闻关键词替代
    "稀土":   [],             # 无期货，由新闻关键词替代
    "电池":   [],             # 无期货，由新闻关键词替代
}

C4_THRESHOLD_PCT = 20.0


def get_commodity_price_change(industry: str) -> dict[str, Any]:
    """
    获取指定行业的商品期货近3个月价格涨幅

    Returns:
        {industry, symbols, max_pct_change_3m, meets_c4, detail, error}
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
            if "date" not in df.columns:
                df = df.rename(columns={df.columns[0]: "date"})
            if "close" not in df.columns and "收盘价" in df.columns:
                df = df.rename(columns={"收盘价": "close"})
            if "close" not in df.columns:
                df = df.rename(columns={df.columns[4]: "close"})

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df = df.dropna(subset=["close"])

            if len(df) < 2:
                detail.append({"symbol": symbol, "error": "数据量不足"})
                continue

            cutoff_date = datetime.now() - timedelta(days=90)
            recent = df[df["date"] >= cutoff_date]
            if len(recent) < 2:
                recent = df.tail(63)

            start_price = float(recent["close"].iloc[0])
            end_price = float(recent["close"].iloc[-1])

            if start_price <= 0:
                detail.append({"symbol": symbol, "error": "起始价格异常"})
                continue

            pct_change = round((end_price - start_price) / start_price * 100, 2)
            detail.append(
                {
                    "symbol": symbol,
                    "start_price": start_price,
                    "end_price": end_price,
                    "pct_change_3m": pct_change,
                    "start_date": recent["date"].iloc[0].strftime("%Y-%m-%d"),
                    "end_date": recent["date"].iloc[-1].strftime("%Y-%m-%d"),
                }
            )

            if max_pct is None or pct_change > max_pct:
                max_pct = pct_change

        except Exception as e:
            logger.debug(f"获取 {symbol} 期货价格失败: {e}")
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
    扫描所有行业，返回满足 C4 条件（近3个月涨幅≥20%）的行业列表
    """
    triggered = []
    for industry in COMMODITY_FUTURES_MAP:
        result = get_commodity_price_change(industry)
        if result["meets_c4"]:
            triggered.append(result)
    return triggered
