"""
市场初筛工具（Python纯规则，0 LLM token）

流程：
1. 获取今日A股涨幅前N名
2. 基础过滤（排除ST / 涨停 / 高换手 / 小市值）
3. 异步批量获取行业信息
"""

import asyncio
from typing import Any

import akshare as ak


def _limit_up_threshold(code: str) -> float:
    """不同板块涨停阈值"""
    if code.startswith("688") or code.startswith("300") or code.startswith("301"):
        return 19.8
    elif code.startswith("8") or code.startswith("43"):
        return 29.8
    return 9.8


def get_top_gainers(top_n: int = 50) -> list[dict[str, Any]]:
    """
    获取今日A股涨幅前N名

    Returns:
        list of dict: 代码/名称/最新价/涨跌幅/换手率/流通市值/总市值
    """
    df = ak.stock_zh_a_spot_em()
    df = df.sort_values("涨跌幅", ascending=False).head(top_n)

    result = []
    for _, row in df.iterrows():
        result.append({
            "代码": str(row["代码"]).zfill(6),
            "名称": str(row["名称"]),
            "最新价": float(row.get("最新价", 0) or 0),
            "涨跌幅": float(row.get("涨跌幅", 0) or 0),
            "换手率": float(row.get("换手率", 0) or 0),
            "流通市值": float(row.get("流通市值", 0) or 0),
            "总市值": float(row.get("总市值", 0) or 0),
        })
    return result


def basic_filter(
    stocks: list[dict[str, Any]],
    min_float_mv_yi: float = 30.0,
    max_turnover: float = 20.0,
) -> list[dict[str, Any]]:
    """
    Python规则初筛（0 token）

    过滤规则：
    - 排除 ST / *ST / 退市风险（名称含ST或退）
    - 排除涨停（已涨完，追高风险大）
    - 排除换手率 > max_turnover%（游资短线炒作）
    - 排除流通市值 < min_float_mv_yi 亿（流动性差）
    """
    filtered = []
    for s in stocks:
        code = s["代码"]
        name = s["名称"]
        pct = s["涨跌幅"]
        turnover = s["换手率"]
        float_mv_yi = s["流通市值"] / 1e8

        if "ST" in name or "退" in name:
            continue
        if pct >= _limit_up_threshold(code):
            continue
        if turnover > max_turnover:
            continue
        if float_mv_yi < min_float_mv_yi:
            continue

        s["流通市值(亿)"] = round(float_mv_yi, 2)
        filtered.append(s)

    return filtered


async def enrich_with_industry(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    异步并行获取各股票行业信息（使用 asyncio.to_thread 并发调用同步接口）
    """
    async def fetch_one(s: dict) -> dict:
        try:
            df = await asyncio.to_thread(ak.stock_individual_info_em, symbol=s["代码"])
            info = dict(zip(df["item"], df["value"]))
            s["行业"] = info.get("行业", "未知")
        except Exception:
            s["行业"] = "未知"
        return s

    return list(await asyncio.gather(*[fetch_one(s) for s in stocks]))
