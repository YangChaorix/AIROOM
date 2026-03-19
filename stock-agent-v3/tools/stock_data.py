"""
股票基础数据工具：基本信息、财务指标、历史K线
供 screener_agent 使用
"""

import json
import traceback
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd

from config.settings import settings


def _fmt_date(date: datetime) -> str:
    return date.strftime("%Y%m%d")


def get_stock_basic_info(stock_code: str) -> dict:
    """获取股票基本信息"""
    try:
        df = ak.stock_individual_info_em(symbol=stock_code)
        if df is None or df.empty:
            return {"error": f"未找到 {stock_code} 基本信息"}

        info = {}
        if "item" in df.columns and "value" in df.columns:
            for _, row in df.iterrows():
                info[str(row["item"])] = str(row["value"])
        else:
            info = df.to_dict(orient="list")

        # 格式化市值为亿
        try:
            info["总市值(亿)"] = str(round(float(info.get("总市值", 0)) / 1e8, 2))
            info["流通市值(亿)"] = str(round(float(info.get("流通市值", 0)) / 1e8, 2))
        except Exception:
            pass

        # 近期涨跌幅
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=10)
            hist_df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=_fmt_date(start_date),
                end_date=_fmt_date(end_date),
                adjust="qfq",
            )
            if hist_df is not None and len(hist_df) >= 1:
                col_map = {"涨跌幅": "pct_change", "换手率": "turnover_rate"}
                hist_df = hist_df.rename(
                    columns={k: v for k, v in col_map.items() if k in hist_df.columns}
                )
                last = hist_df.iloc[-1]
                info["今日涨跌幅(%)"] = str(round(float(last.get("pct_change", 0)), 2))
                info["今日换手率(%)"] = str(round(float(last.get("turnover_rate", 0)), 2))
        except Exception:
            pass

        info["股票代码"] = stock_code
        return info
    except Exception as e:
        return {"error": str(e), "股票代码": stock_code}


def get_financial_indicators(stock_code: str) -> dict:
    """获取财务指标（PE、PB、ROE、毛利率等）"""
    result = {"股票代码": stock_code}

    try:
        profit_df = ak.stock_financial_abstract_ths(symbol=stock_code, indicator="按年度")
        if profit_df is not None and not profit_df.empty:
            if "报告期" in profit_df.columns:
                profit_df = profit_df.sort_values("报告期", ascending=False)
            recent = profit_df.head(4)
            rows = []
            for _, row in recent.iterrows():
                record = {
                    col: (
                        str(row[col])
                        if not (isinstance(row[col], float) and pd.isna(row[col]))
                        else "N/A"
                    )
                    for col in recent.columns
                }
                rows.append(record)
            result["财务摘要(近4期)"] = rows
    except Exception as e:
        result["财务摘要获取失败"] = str(e)

    try:
        ind_df = ak.stock_financial_analysis_indicator(symbol=stock_code, start_year="2022")
        if ind_df is not None and not ind_df.empty:
            cols = ["日期", "净资产收益率", "总资产报酬率", "净利率", "毛利率", "资产负债率"]
            rows = []
            for _, row in ind_df.head(6).iterrows():
                record = {col: str(row[col]) for col in cols if col in ind_df.columns}
                rows.append(record)
            result["盈利能力(近6期)"] = rows
    except Exception as e:
        result["盈利能力获取失败"] = str(e)

    return result


def get_historical_volume(stock_code: str, days: int = 30) -> dict:
    """
    获取历史成交量数据，计算近3日均量 vs 过去20日均量的倍数
    用于 D5 技术突破信号评分
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=max(days, 60))
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=_fmt_date(start_date),
            end_date=_fmt_date(end_date),
            adjust="qfq",
        )
        if df is None or df.empty:
            return {"error": "无法获取K线数据"}

        col_map = {
            "成交量": "volume",
            "换手率": "turnover_rate",
            "涨跌幅": "pct_change",
            "收盘": "close",
            "最高": "high",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        for col in ["volume", "turnover_rate", "pct_change", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["volume"]).reset_index(drop=True)

        if len(df) < 5:
            return {"error": "数据量不足"}

        recent3_vol = float(df["volume"].tail(3).mean())
        ma20_vol = (
            float(df["volume"].tail(20).mean())
            if len(df) >= 20
            else float(df["volume"].mean())
        )
        vol_ratio = round(recent3_vol / ma20_vol, 2) if ma20_vol > 0 else 0

        # 判断 D5 得分
        if vol_ratio >= 5:
            d5_score = 3
            d5_signal = f"近3日均量是20日均量的{vol_ratio}倍，强力放量突破"
        elif vol_ratio >= 2:
            d5_score = 2
            d5_signal = f"近3日均量是20日均量的{vol_ratio}倍，成交量明显放大"
        elif vol_ratio >= 1.2:
            d5_score = 1
            d5_signal = f"近3日均量是20日均量的{vol_ratio}倍，成交量小幅放大"
        else:
            d5_score = 0
            d5_signal = f"近3日均量是20日均量的{vol_ratio}倍，无明显放量"

        # 近期最高价 vs 当前收盘
        current_close = float(df["close"].iloc[-1]) if "close" in df.columns else None
        max_60d = (
            float(df["close"].tail(60).max())
            if "close" in df.columns and len(df) >= 10
            else None
        )
        near_high = current_close and max_60d and current_close >= max_60d * 0.98

        return {
            "股票代码": stock_code,
            "近3日均量": round(recent3_vol, 0),
            "20日均量": round(ma20_vol, 0),
            "量比倍数(3日/20日均)": vol_ratio,
            "D5得分": d5_score,
            "D5信号": d5_signal,
            "近60日最高价": max_60d,
            "当前收盘价": current_close,
            "是否接近60日高点": near_high,
        }
    except Exception as e:
        return {"error": str(e), "股票代码": stock_code}
