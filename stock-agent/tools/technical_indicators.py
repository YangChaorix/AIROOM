"""
技术指标计算工具模块
计算常用技术指标：MA、MACD、RSI、布林带、KDJ、成交量分析等
封装为 LangChain Tool 供 Agent 使用
"""

import json
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import akshare as ak
import numpy as np
import pandas as pd
from langchain_core.tools import tool

from config.settings import settings


def _get_kline_data(stock_code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """
    获取K线数据用于技术指标计算
    内部辅助函数，不暴露为Tool

    Args:
        stock_code: 股票代码
        days: 获取天数（需要足够多的数据计算指标）

    Returns:
        包含OHLCV数据的DataFrame，失败返回None
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq",
        )

        if df is None or df.empty:
            return None

        # 统一列名
        col_map = {
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
            "涨跌幅": "pct_change", "换手率": "turnover_rate"
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        df = df.sort_values("date").reset_index(drop=True)

        # 确保数值列为 float
        for col in ["open", "close", "high", "low", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    except Exception:
        return None


def _calc_ma(close: pd.Series, periods: List[int]) -> Dict[str, float]:
    """计算多周期移动平均线"""
    result = {}
    for p in periods:
        if len(close) >= p:
            result[f"MA{p}"] = round(float(close.rolling(window=p).mean().iloc[-1]), 4)
        else:
            result[f"MA{p}"] = None
    return result


def _calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict[str, Optional[float]]:
    """
    计算 MACD 指标
    MACD = EMA(fast) - EMA(slow)
    Signal = EMA(MACD, signal)
    Histogram = MACD - Signal
    """
    if len(close) < slow + signal:
        return {"MACD": None, "Signal": None, "Histogram": None, "趋势": "数据不足"}

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    macd_val = float(macd_line.iloc[-1])
    signal_val = float(signal_line.iloc[-1])
    hist_val = float(histogram.iloc[-1])

    # 判断趋势
    if macd_val > signal_val and macd_val > 0:
        trend = "强势上涨（MACD金叉+多头区域）"
    elif macd_val > signal_val and macd_val < 0:
        trend = "弱势反弹（MACD金叉但空头区域）"
    elif macd_val < signal_val and macd_val > 0:
        trend = "高位回落（MACD死叉但多头区域）"
    else:
        trend = "下跌趋势（MACD死叉+空头区域）"

    return {
        "MACD": round(macd_val, 4),
        "Signal": round(signal_val, 4),
        "Histogram": round(hist_val, 4),
        "趋势": trend,
    }


def _calc_rsi(close: pd.Series, periods: List[int] = None) -> Dict[str, Optional[float]]:
    """
    计算 RSI 相对强弱指数
    RSI > 70 超买，RSI < 30 超卖
    """
    if periods is None:
        periods = [6, 12, 24]

    result = {}
    for period in periods:
        if len(close) < period + 1:
            result[f"RSI{period}"] = None
            continue

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, float("inf"))
        rsi = 100 - (100 / (1 + rs))

        rsi_val = float(rsi.iloc[-1])
        result[f"RSI{period}"] = round(rsi_val, 2)

    # 综合研判
    rsi6 = result.get("RSI6")
    if rsi6 is not None:
        if rsi6 > 80:
            result["RSI研判"] = "严重超买，注意回调风险"
        elif rsi6 > 70:
            result["RSI研判"] = "超买区间，短期或有调整"
        elif rsi6 < 20:
            result["RSI研判"] = "严重超卖，可能存在反弹机会"
        elif rsi6 < 30:
            result["RSI研判"] = "超卖区间，关注反弹信号"
        else:
            result["RSI研判"] = "正常区间"

    return result


def _calc_bollinger_bands(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> Dict[str, Optional[float]]:
    """
    计算布林带（Bollinger Bands）
    上轨 = MA20 + 2*std
    中轨 = MA20
    下轨 = MA20 - 2*std
    """
    if len(close) < period:
        return {"上轨": None, "中轨": None, "下轨": None, "带宽": None, "位置": None}

    rolling_mean = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()

    upper = rolling_mean + num_std * rolling_std
    middle = rolling_mean
    lower = rolling_mean - num_std * rolling_std

    current_price = float(close.iloc[-1])
    upper_val = float(upper.iloc[-1])
    middle_val = float(middle.iloc[-1])
    lower_val = float(lower.iloc[-1])
    bandwidth = round((upper_val - lower_val) / middle_val * 100, 2)

    # 价格在布林带中的位置（0=下轨, 100=上轨）
    if upper_val != lower_val:
        position = round((current_price - lower_val) / (upper_val - lower_val) * 100, 1)
    else:
        position = 50.0

    # 判断
    if current_price >= upper_val:
        signal = "价格触及上轨，注意回调风险"
    elif current_price <= lower_val:
        signal = "价格触及下轨，可能存在支撑"
    elif position > 70:
        signal = "价格偏向上轨，偏强势"
    elif position < 30:
        signal = "价格偏向下轨，偏弱势"
    else:
        signal = "价格运行在布林带中间区域"

    return {
        "上轨(Boll_Upper)": round(upper_val, 4),
        "中轨(Boll_Middle)": round(middle_val, 4),
        "下轨(Boll_Lower)": round(lower_val, 4),
        "带宽(%)": bandwidth,
        "价格位置(%)": position,
        "信号": signal,
    }


def _calc_kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 9,
) -> Dict[str, Optional[float]]:
    """
    计算 KDJ 随机指标
    K > 80 超买，K < 20 超卖
    """
    if len(close) < period:
        return {"K": None, "D": None, "J": None, "研判": "数据不足"}

    # 计算 RSV（未成熟随机值）
    lowest_low = low.rolling(window=period).min()
    highest_high = high.rolling(window=period).max()

    rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100

    # 计算 K、D、J
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d

    k_val = round(float(k.iloc[-1]), 2)
    d_val = round(float(d.iloc[-1]), 2)
    j_val = round(float(j.iloc[-1]), 2)

    # 研判
    if k_val > d_val and k_val < 80:
        judgment = "KDJ金叉，多头信号"
    elif k_val < d_val and k_val > 20:
        judgment = "KDJ死叉，空头信号"
    elif k_val > 80:
        judgment = "KDJ超买，谨慎追高"
    elif k_val < 20:
        judgment = "KDJ超卖，关注做多机会"
    else:
        judgment = "KDJ中性区间"

    return {"K": k_val, "D": d_val, "J": j_val, "研判": judgment}


def _calc_volume_analysis(
    volume: pd.Series, close: pd.Series
) -> Dict[str, object]:
    """成交量分析：量价关系、成交量趋势"""
    if len(volume) < 20:
        return {"分析": "数据不足"}

    current_vol = float(volume.iloc[-1])
    ma5_vol = float(volume.rolling(5).mean().iloc[-1])
    ma20_vol = float(volume.rolling(20).mean().iloc[-1])

    vol_ratio_5 = round(current_vol / ma5_vol, 2) if ma5_vol > 0 else None
    vol_ratio_20 = round(current_vol / ma20_vol, 2) if ma20_vol > 0 else None

    # 价量关系
    price_change = float(close.iloc[-1]) - float(close.iloc[-2]) if len(close) > 1 else 0
    if price_change > 0 and current_vol > ma5_vol:
        volume_price_relation = "价涨量增，强势上涨"
    elif price_change > 0 and current_vol < ma5_vol:
        volume_price_relation = "价涨量缩，上涨动能不足"
    elif price_change < 0 and current_vol > ma5_vol:
        volume_price_relation = "价跌量增，看空信号"
    elif price_change < 0 and current_vol < ma5_vol:
        volume_price_relation = "价跌量缩，可能到底部"
    else:
        volume_price_relation = "量价关系中性"

    return {
        "今日成交量": int(current_vol),
        "5日均量": round(ma5_vol, 0),
        "20日均量": round(ma20_vol, 0),
        "量比(vs5日均)": vol_ratio_5,
        "量比(vs20日均)": vol_ratio_20,
        "价量关系": volume_price_relation,
    }


def _identify_support_resistance(
    high: pd.Series, low: pd.Series, close: pd.Series
) -> Dict[str, object]:
    """识别关键支撑位和压力位（基于近期高低点）"""
    if len(close) < 20:
        return {"支撑位": [], "压力位": []}

    recent_high = float(high.tail(60).max())
    recent_low = float(low.tail(60).min())
    current = float(close.iloc[-1])

    # 基于斐波那契回调识别关键位
    diff = recent_high - recent_low
    levels = {
        "近60日最高价(压力)": round(recent_high, 3),
        "近60日最低价(支撑)": round(recent_low, 3),
        "斐波那契61.8%": round(recent_low + diff * 0.618, 3),
        "斐波那契50%": round(recent_low + diff * 0.5, 3),
        "斐波那契38.2%": round(recent_low + diff * 0.382, 3),
        "当前价格": round(current, 3),
    }

    # 找出当前价格上方的压力位和下方的支撑位
    support_levels = []
    resistance_levels = []
    for name, level in levels.items():
        if name in ["近60日最低价(支撑)", "斐波那契38.2%", "斐波那契50%"]:
            if level < current:
                support_levels.append({"位置": name, "价格": level})
        elif name in ["近60日最高价(压力)", "斐波那契61.8%"]:
            if level > current:
                resistance_levels.append({"位置": name, "价格": level})

    return {
        "当前价格": round(current, 3),
        "关键支撑位": support_levels,
        "关键压力位": resistance_levels,
        "完整关键位": levels,
    }


@tool
def calculate_technical_indicators(stock_code: str) -> str:
    """
    计算股票全套技术指标，包括均线(MA)、MACD、RSI、布林带(Boll)、KDJ、成交量分析、支撑压力位。

    Args:
        stock_code: A股股票代码，如 '000001' 或 '600519'

    Returns:
        JSON格式的技术指标分析结果字符串
    """
    try:
        # 获取足够的历史数据（至少120天以保证指标计算准确）
        df = _get_kline_data(stock_code, days=180)

        if df is None or df.empty:
            return json.dumps({"error": f"无法获取股票 {stock_code} 的K线数据"}, ensure_ascii=False)

        close = df["close"]
        high = df["high"] if "high" in df.columns else close
        low = df["low"] if "low" in df.columns else close
        volume = df["volume"] if "volume" in df.columns else pd.Series([0] * len(close))

        result = {
            "股票代码": stock_code,
            "计算日期": datetime.now().strftime("%Y-%m-%d"),
            "数据条数": len(df),
            "当前收盘价": round(float(close.iloc[-1]), 4),
        }

        # 1. 移动平均线
        result["均线指标(MA)"] = _calc_ma(close, [5, 10, 20, 30, 60, 120])

        # 均线多空排列判断
        ma_vals = result["均线指标(MA)"]
        current_price = float(close.iloc[-1])
        if (ma_vals.get("MA5") and ma_vals.get("MA10") and ma_vals.get("MA20") and
                ma_vals["MA5"] > ma_vals["MA10"] > ma_vals["MA20"]):
            ma_trend = "多头排列（强势）"
        elif (ma_vals.get("MA5") and ma_vals.get("MA10") and ma_vals.get("MA20") and
              ma_vals["MA5"] < ma_vals["MA10"] < ma_vals["MA20"]):
            ma_trend = "空头排列（弱势）"
        else:
            ma_trend = "均线纠缠（震荡）"
        result["均线研判"] = ma_trend
        result["价格与均线关系"] = {
            "价格在MA5之上" if current_price > (ma_vals.get("MA5") or 0) else "价格在MA5之下": True,
            "价格在MA20之上" if current_price > (ma_vals.get("MA20") or 0) else "价格在MA20之下": True,
            "价格在MA60之上" if current_price > (ma_vals.get("MA60") or 0) else "价格在MA60之下": True,
        }

        # 2. MACD 指标
        result["MACD指标"] = _calc_macd(close)

        # 3. RSI 相对强弱指数
        result["RSI指标"] = _calc_rsi(close, [6, 12, 24])

        # 4. 布林带
        result["布林带(Boll)"] = _calc_bollinger_bands(close)

        # 5. KDJ 随机指标
        result["KDJ指标"] = _calc_kdj(high, low, close)

        # 6. 成交量分析
        result["成交量分析"] = _calc_volume_analysis(volume, close)

        # 7. 支撑压力位
        result["支撑压力位"] = _identify_support_resistance(high, low, close)

        # 8. 综合技术信号
        bullish_signals = []
        bearish_signals = []

        macd_data = result["MACD指标"]
        if macd_data.get("MACD") and macd_data.get("Signal"):
            if macd_data["MACD"] > macd_data["Signal"]:
                bullish_signals.append("MACD金叉")
            else:
                bearish_signals.append("MACD死叉")

        rsi_data = result["RSI指标"]
        rsi6 = rsi_data.get("RSI6")
        if rsi6:
            if rsi6 < 30:
                bullish_signals.append("RSI超卖")
            elif rsi6 > 70:
                bearish_signals.append("RSI超买")

        if "多头排列" in ma_trend:
            bullish_signals.append("均线多头排列")
        elif "空头排列" in ma_trend:
            bearish_signals.append("均线空头排列")

        result["综合技术信号"] = {
            "看多信号": bullish_signals,
            "看空信号": bearish_signals,
            "信号强度": f"看多{len(bullish_signals)}个 vs 看空{len(bearish_signals)}个",
        }

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": f"计算股票 {stock_code} 技术指标失败: {str(e)}",
            "traceback": traceback.format_exc()
        }, ensure_ascii=False)
