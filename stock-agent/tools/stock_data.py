"""
股票数据工具模块
使用 akshare 获取 A股基本信息、财务指标、历史K线数据
封装为 LangChain Tool 供 Agent 使用
"""

import json
import traceback
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd
from langchain_core.tools import tool

from config.settings import settings


def _format_date(date: datetime) -> str:
    """格式化日期为 akshare 要求的字符串格式"""
    return date.strftime("%Y%m%d")


def _safe_get_value(df: pd.DataFrame, column: str, default: str = "N/A") -> str:
    """安全地从 DataFrame 获取值，避免因列不存在或空值报错"""
    try:
        if column in df.columns and not df[column].empty:
            val = df[column].iloc[-1]
            if pd.isna(val):
                return default
            return str(val)
    except Exception:
        pass
    return default


@tool
def get_stock_basic_info(stock_code: str) -> str:
    """
    获取股票基本信息，包括股票名称、所属行业、总市值、流通市值、上市日期等。

    Args:
        stock_code: A股股票代码，如 '000001'（平安银行）或 '600519'（贵州茅台）

    Returns:
        JSON格式的股票基本信息字符串
    """
    try:
        # 获取 A 股所有股票基本信息
        stock_info_df = ak.stock_individual_info_em(symbol=stock_code)

        if stock_info_df is None or stock_info_df.empty:
            return json.dumps({"error": f"未找到股票 {stock_code} 的基本信息"}, ensure_ascii=False)

        # stock_individual_info_em 返回格式为 item/value 两列
        info_dict = {}
        if "item" in stock_info_df.columns and "value" in stock_info_df.columns:
            for _, row in stock_info_df.iterrows():
                info_dict[str(row["item"])] = str(row["value"])
        else:
            # 备选：直接转为字典
            info_dict = stock_info_df.to_dict(orient="list")

        # 获取实时行情（补充市值数据）
        try:
            realtime_df = ak.stock_zh_a_spot_em()
            if realtime_df is not None and not realtime_df.empty:
                stock_realtime = realtime_df[realtime_df["代码"] == stock_code]
                if not stock_realtime.empty:
                    row = stock_realtime.iloc[0]
                    info_dict.update({
                        "最新价": str(row.get("最新价", "N/A")),
                        "涨跌幅": str(row.get("涨跌幅", "N/A")) + "%",
                        "总市值(亿)": str(round(float(row.get("总市值", 0)) / 1e8, 2))
                        if row.get("总市值") not in [None, "N/A"] else "N/A",
                        "流通市值(亿)": str(round(float(row.get("流通市值", 0)) / 1e8, 2))
                        if row.get("流通市值") not in [None, "N/A"] else "N/A",
                        "市盈率(动态)": str(row.get("市盈率-动态", "N/A")),
                        "市净率": str(row.get("市净率", "N/A")),
                        "60日涨跌幅": str(row.get("60日涨跌幅", "N/A")) + "%",
                        "年初至今涨跌幅": str(row.get("年初至今涨跌幅", "N/A")) + "%",
                    })
        except Exception as e:
            info_dict["实时行情获取失败"] = str(e)

        info_dict["股票代码"] = stock_code
        return json.dumps(info_dict, ensure_ascii=False, indent=2)

    except Exception as e:
        error_msg = f"获取股票 {stock_code} 基本信息失败: {str(e)}"
        return json.dumps({"error": error_msg, "traceback": traceback.format_exc()}, ensure_ascii=False)


@tool
def get_financial_indicators(stock_code: str) -> str:
    """
    获取股票财务指标，包括PE、PB、ROE、ROA、营收、净利润、毛利率、净利率等关键财务数据。

    Args:
        stock_code: A股股票代码，如 '000001' 或 '600519'

    Returns:
        JSON格式的财务指标字符串，包含近几年数据
    """
    try:
        result = {}

        # 1. 获取主要财务指标（ROE、ROA、毛利率等）
        try:
            profit_df = ak.stock_financial_abstract_ths(symbol=stock_code, indicator="按年度")
            if profit_df is not None and not profit_df.empty:
                # 取最近4期数据
                recent = profit_df.head(4)
                financial_list = []
                for _, row in recent.iterrows():
                    record = {}
                    for col in recent.columns:
                        val = row[col]
                        record[col] = str(val) if not pd.isna(val) else "N/A"
                    financial_list.append(record)
                result["财务摘要(近4期)"] = financial_list
        except Exception as e:
            result["财务摘要获取失败"] = str(e)

        # 2. 获取盈利能力数据
        try:
            indicator_df = ak.stock_financial_analysis_indicator(symbol=stock_code, start_year="2021")
            if indicator_df is not None and not indicator_df.empty:
                recent = indicator_df.head(8)
                indicators_list = []
                for _, row in recent.iterrows():
                    record = {}
                    for col in ["日期", "净资产收益率", "总资产报酬率", "净利率", "毛利率",
                                "资产负债率", "流动比率", "速动比率"]:
                        if col in recent.columns:
                            val = row[col]
                            record[col] = str(val) if not pd.isna(val) else "N/A"
                    indicators_list.append(record)
                result["盈利能力指标(近8期)"] = indicators_list
        except Exception as e:
            result["盈利能力指标获取失败"] = str(e)

        # 3. 获取实时估值数据（PE、PB）
        try:
            realtime_df = ak.stock_zh_a_spot_em()
            if realtime_df is not None and not realtime_df.empty:
                stock_row = realtime_df[realtime_df["代码"] == stock_code]
                if not stock_row.empty:
                    r = stock_row.iloc[0]
                    result["实时估值"] = {
                        "市盈率(TTM)": str(r.get("市盈率-动态", "N/A")),
                        "市净率": str(r.get("市净率", "N/A")),
                        "最新价": str(r.get("最新价", "N/A")),
                        "成交量(手)": str(r.get("成交量", "N/A")),
                        "成交额(元)": str(r.get("成交额", "N/A")),
                    }
        except Exception as e:
            result["实时估值获取失败"] = str(e)

        if not result:
            return json.dumps({"error": f"未能获取股票 {stock_code} 的财务数据"}, ensure_ascii=False)

        result["股票代码"] = stock_code
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({
            "error": f"获取股票 {stock_code} 财务指标失败: {str(e)}",
            "traceback": traceback.format_exc()
        }, ensure_ascii=False)


@tool
def get_historical_kline(stock_code: str, days: Optional[int] = None) -> str:
    """
    获取股票历史K线数据（日线），包含开高低收、成交量、成交额等。

    Args:
        stock_code: A股股票代码，如 '000001' 或 '600519'
        days: 获取最近多少天的数据，默认使用配置文件中的值（90天）

    Returns:
        JSON格式的历史K线数据字符串
    """
    try:
        if days is None:
            days = settings.akshare.kline_days

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # 获取历史K线数据（前复权）
        kline_df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period="daily",
            start_date=_format_date(start_date),
            end_date=_format_date(end_date),
            adjust="qfq",  # 前复权
        )

        if kline_df is None or kline_df.empty:
            return json.dumps({"error": f"未找到股票 {stock_code} 的历史数据"}, ensure_ascii=False)

        # 重命名列（兼容不同版本akshare）
        column_mapping = {
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "成交额": "amount", "振幅": "amplitude",
            "涨跌幅": "pct_change", "涨跌额": "change",
            "换手率": "turnover_rate"
        }
        kline_df = kline_df.rename(columns={k: v for k, v in column_mapping.items() if k in kline_df.columns})

        # 数值格式化
        kline_df = kline_df.round(4)

        # 基础统计信息
        stats = {
            "股票代码": stock_code,
            "数据区间": f"{_format_date(start_date)} ~ {_format_date(end_date)}",
            "交易日数量": len(kline_df),
            "区间最高价": float(kline_df["high"].max()) if "high" in kline_df.columns else "N/A",
            "区间最低价": float(kline_df["low"].min()) if "low" in kline_df.columns else "N/A",
            "最新收盘价": float(kline_df["close"].iloc[-1]) if "close" in kline_df.columns else "N/A",
            "区间涨跌幅(%)": round(
                (kline_df["close"].iloc[-1] - kline_df["close"].iloc[0]) / kline_df["close"].iloc[0] * 100, 2
            ) if "close" in kline_df.columns and len(kline_df) > 1 else "N/A",
            "平均成交量": float(kline_df["volume"].mean()) if "volume" in kline_df.columns else "N/A",
        }

        # 最近20天的K线数据（避免数据量过大）
        recent_kline = kline_df.tail(20).to_dict(orient="records")
        # 确保所有值可序列化
        for record in recent_kline:
            for k, v in record.items():
                if pd.isna(v) if isinstance(v, float) else False:
                    record[k] = None

        result = {
            "统计信息": stats,
            "最近20日K线": recent_kline,
            "完整数据条数": len(kline_df),
        }

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": f"获取股票 {stock_code} 历史K线失败: {str(e)}",
            "traceback": traceback.format_exc()
        }, ensure_ascii=False)
