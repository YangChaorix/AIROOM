"""
技术指标工具：成交量/换手率分析，供 screener_agent D5 维度使用
"""

import tools.proxy_patch  # noqa: F401 — 修复 Clash Fake-IP 模式下 requests 走系统代理的问题
import json
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd


import logging as _logging
_logger = _logging.getLogger(__name__)

_COL_MAP_EM = {
    "日期": "date", "开盘": "open", "收盘": "close",
    "最高": "high", "最低": "low", "成交量": "volume",
    "成交额": "amount", "涨跌幅": "pct_change", "换手率": "turnover_rate",
}


def _get_kline(stock_code: str, days: int = 60) -> Optional[pd.DataFrame]:
    """
    获取 A 股日 K 线数据。
    优先调用东方财富（stock_zh_a_hist），失败时回退到腾讯（stock_zh_a_hist_tx）。
    返回标准化 DataFrame，含 date/open/close/high/low/volume 列。
    """
    end = datetime.now()
    start = end - timedelta(days=days)
    start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    # ── 方案1：东方财富（K线专用接口，部分网络环境可用）──
    try:
        df = ak.stock_zh_a_hist(
            symbol=stock_code, period="daily",
            start_date=start_s, end_date=end_s, adjust="qfq",
        )
        if df is not None and not df.empty:
            df = df.rename(columns={k: v for k, v in _COL_MAP_EM.items() if k in df.columns})
            for col in ["open", "close", "high", "low", "volume", "turnover_rate"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        _logger.debug(f"[{stock_code}] EM K线失败，切换腾讯接口: {e}")

    # ── 方案2：腾讯（稳定备用，无成交量字段，用成交额/收盘价近似）──
    try:
        prefix = "sh" if stock_code.startswith(("6", "9")) else "sz"
        df = ak.stock_zh_a_hist_tx(
            symbol=f"{prefix}{stock_code}",
            start_date=start_s, end_date=end_s,
        )
        if df is None or df.empty:
            return None
        for col in ["open", "close", "high", "low", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # 用成交额 / 收盘价 近似成交量（量比精度略低，但趋势判断可用）
        if "amount" in df.columns and "close" in df.columns:
            df["volume"] = df["amount"] / df["close"].replace(0, float("nan"))
        _logger.debug(f"[{stock_code}] 腾讯K线成功，共{len(df)}行")
        return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        _logger.warning(f"[{stock_code}] 腾讯K线也失败: {e}")
        return None


def calc_volume_breakthrough(stock_code: str) -> dict:
    """
    计算 D5 技术突破信号：
    - 近3日均量 / 过去20日均量 是否 ≥5倍
    - 日/周换手率是否明显放大
    - 股价是否突破近期高点
    """
    df = _get_kline(stock_code, days=90)
    if df is None or len(df) < 10:
        return {"stock_code": stock_code, "error": "数据不足", "d5_score": 0}

    vol = df["volume"]
    recent3_avg = float(vol.tail(3).mean())
    ma20_avg = float(vol.tail(20).mean()) if len(df) >= 20 else float(vol.mean())
    vol_ratio = round(recent3_avg / ma20_avg, 2) if ma20_avg > 0 else 0

    # 换手率分析
    turnover_info = {}
    if "turnover_rate" in df.columns:
        recent_tr = float(df["turnover_rate"].tail(3).mean())
        avg_tr = float(df["turnover_rate"].mean())
        turnover_info = {
            "近3日均换手率(%)": round(recent_tr, 2),
            "历史平均换手率(%)": round(avg_tr, 2),
            "换手率放大倍数": round(recent_tr / avg_tr, 2) if avg_tr > 0 else 0,
        }

    # 股价突破
    if "close" in df.columns:
        current = float(df["close"].iloc[-1])
        high_60d = (
            float(df["close"].tail(60).max())
            if len(df) >= 30
            else float(df["close"].max())
        )
        price_breakthrough = current >= high_60d * 0.98
    else:
        current, high_60d, price_breakthrough = None, None, False

    # D5 评分
    if vol_ratio >= 5 and price_breakthrough:
        d5_score = 3
        d5_desc = f"近3日均量是20日均量的{vol_ratio}倍，股价突破近期高点，强力突破信号"
    elif vol_ratio >= 5 or (vol_ratio >= 2 and price_breakthrough):
        d5_score = 2
        d5_desc = f"近3日均量是20日均量的{vol_ratio}倍，成交量放大明显"
    elif vol_ratio >= 1.5:
        d5_score = 1
        d5_desc = f"近3日均量是20日均量的{vol_ratio}倍，成交量小幅放大"
    else:
        d5_score = 0
        d5_desc = f"近3日均量是20日均量的{vol_ratio}倍，无明显放量"

    return {
        "stock_code": stock_code,
        "近3日均量": round(recent3_avg, 0),
        "20日均量": round(ma20_avg, 0),
        "量比(3日/20日)": vol_ratio,
        "当前收盘价": current,
        "60日最高价": high_60d,
        "股价接近60日高点": price_breakthrough,
        "换手率": turnover_info,
        "d5_score": d5_score,
        "d5_desc": d5_desc,
    }


def calc_long_term_trend(stock_code: str) -> dict:
    """
    分析中长期上涨趋势（D4维度辅助）
    - 60/120/250日均线排列
    - 近6个月涨幅
    """
    df = _get_kline(stock_code, days=400)  # 多拉一些确保 250 个交易日够用
    if df is None or len(df) < 30:
        return {"stock_code": stock_code, "error": "数据不足", "d4_hint": "无法判断"}

    close = df["close"]
    current = float(close.iloc[-1])

    ma60 = float(close.tail(60).mean()) if len(close) >= 60 else None
    ma120 = float(close.tail(120).mean()) if len(close) >= 120 else None
    ma250 = float(close.tail(250).mean()) if len(close) >= 250 else None

    # 6个月涨幅
    six_mo_ago = (
        float(close.iloc[-130]) if len(close) >= 130 else float(close.iloc[0])
    )
    six_mo_pct = round((current - six_mo_ago) / six_mo_ago * 100, 2)

    # 均线多头排列
    if ma60 and ma120 and current > ma60 > ma120:
        trend_desc = "均线多头排列，中期上升趋势"
        bullish = True
    elif ma60 and current < ma60:
        trend_desc = "价格在60日均线下方，趋势偏弱"
        bullish = False
    else:
        trend_desc = "趋势中性或震荡"
        bullish = False

    return {
        "stock_code": stock_code,
        "当前价": round(current, 3),
        "MA60": round(ma60, 3) if ma60 else None,
        "MA120": round(ma120, 3) if ma120 else None,
        "MA250": round(ma250, 3) if ma250 else None,
        "近6个月涨幅(%)": six_mo_pct,
        "趋势描述": trend_desc,
        "是否多头排列": bullish,
    }
