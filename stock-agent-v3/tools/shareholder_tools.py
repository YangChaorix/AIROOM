"""
股东结构数据工具：前十大流通股股东分析
用于 screener_agent D3 维度评分
"""

import json
import traceback
from datetime import datetime

import akshare as ak
import pandas as pd


def _classify_holder(name: str, nature: str = "") -> str:
    name = str(name)
    nature = str(nature)

    if "国有股" in nature or "国家股" in nature:
        return "国资"
    if "境外" in nature or "HKSCC" in name or "香港中央" in name:
        return "外资/北向"
    if any(kw in name for kw in ["社保", "保险", "养老", "全国社保"]):
        return "社保/保险"
    if any(
        kw in name
        for kw in [
            "中央汇金",
            "汇金",
            "财政部",
            "国资委",
            "省国有资本",
            "国家队",
            "诚通",
            "中国国新",
        ]
    ):
        return "国资"
    if any(
        kw in name
        for kw in [
            "证券投资基金",
            "ETF",
            "指数基金",
            "华夏基金",
            "易方达",
            "南方基金",
            "嘉实",
            "博时",
            "富国",
            "招商基金",
            "广发基金",
            "工银瑞信",
            "汇添富",
        ]
    ):
        return "公募基金"
    if any(kw in name for kw in ["证券", "银行", "信托"]) and "基金" not in name:
        return "银行/证券/信托"
    if any(kw in name for kw in ["私募", "投资管理", "资产管理", "合伙企业"]):
        return "私募/资管"
    if any(kw in name for kw in ["国家", "国有", "国资", "中央", "政府"]):
        return "国资"
    stripped = name.strip()
    if 2 <= len(stripped) <= 5 and all("\u4e00" <= c <= "\u9fff" for c in stripped):
        return "个人"
    return "其他机构"


def get_top_shareholders(stock_code: str) -> dict:
    """
    获取前十大流通股股东，返回筹码结构分析
    重点判断私募+个人是否超过60%（D3维度）
    """
    try:
        result = {
            "股票代码": stock_code,
            "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        df = ak.stock_circulate_stock_holder(symbol=stock_code)
        if df is None or df.empty:
            return {**result, "error": "无股东数据"}

        if "截止日期" in df.columns:
            latest_date = df["截止日期"].max()
            df = df[df["截止日期"] == latest_date]
            result["数据截止日期"] = str(latest_date)

        df = df.head(10)
        holders = []
        type_stats: dict[str, float] = {}

        for _, row in df.iterrows():
            name = str(row.get("股东名称", ""))
            pct_raw = row.get("占流通股比例", 0)
            try:
                pct = float(str(pct_raw).replace("%", "").strip())
            except Exception:
                pct = 0.0
            nature = str(row.get("股本性质", ""))
            h_type = _classify_holder(name, nature)
            type_stats[h_type] = type_stats.get(h_type, 0.0) + pct
            holders.append(
                {
                    "股东名称": name,
                    "持股数量": str(row.get("持股数量", "N/A")),
                    "占流通股比例(%)": pct,
                    "股本性质": str(row.get("股本性质", "N/A")),
                    "股东类型": h_type,
                }
            )

        result["前十大流通股股东"] = holders

        private_pct = (
            type_stats.get("私募/资管", 0)
            + type_stats.get("个人", 0)
            + type_stats.get("其他机构", 0)
        )
        state_pct = type_stats.get("国资", 0)
        fund_pct = type_stats.get("公募基金", 0)

        # D3 评分
        if private_pct >= 60:
            d3_score = 3
            d3_desc = f"私募+个人持股{round(private_pct,1)}%，超过60%，筹码集中稳定"
        elif private_pct >= 40:
            d3_score = 2
            d3_desc = f"私募+个人持股{round(private_pct,1)}%，在40%-60%之间"
        elif fund_pct > 10:
            d3_score = 1
            d3_desc = f"机构(公募基金)持仓为主，持仓{round(fund_pct,1)}%"
        else:
            d3_score = 0
            d3_desc = "股东结构不符合标准或无法查证"

        result["筹码结构分析"] = {
            "私募+个人持股(%)": round(private_pct, 2),
            "国资持股(%)": round(state_pct, 2),
            "公募基金持股(%)": round(fund_pct, 2),
            "前十合计持股(%)": round(sum(type_stats.values()), 2),
            "是否满足私募+个人>60%": private_pct >= 60,
            "各类型明细": {k: round(v, 2) for k, v in type_stats.items()},
            "D3得分": d3_score,
            "D3描述": d3_desc,
        }
        return result

    except Exception as e:
        return {
            "股票代码": stock_code,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def get_shareholder_changes(stock_code: str) -> dict:
    """获取股东近两期持股变动（连续3季度未减仓判断）"""
    try:
        result = {"股票代码": stock_code}
        df = ak.stock_circulate_stock_holder(symbol=stock_code)
        if df is not None and not df.empty and "截止日期" in df.columns:
            dates = sorted(df["截止日期"].unique(), reverse=True)
            result["可用报告期"] = [str(d) for d in dates[:4]]
            if len(dates) >= 2:
                latest = df[df["截止日期"] == dates[0]][
                    ["股东名称", "占流通股比例"]
                ].set_index("股东名称")
                prev = df[df["截止日期"] == dates[1]][
                    ["股东名称", "占流通股比例"]
                ].set_index("股东名称")
                changes = []
                for name in set(list(latest.index) + list(prev.index)):
                    try:
                        cur_pct = (
                            float(
                                str(latest.loc[name, "占流通股比例"]).replace("%", "")
                            )
                            if name in latest.index
                            else 0
                        )
                        pre_pct = (
                            float(
                                str(prev.loc[name, "占流通股比例"]).replace("%", "")
                            )
                            if name in prev.index
                            else 0
                        )
                        diff = round(cur_pct - pre_pct, 3)
                        if diff != 0:
                            changes.append(
                                {
                                    "股东名称": name,
                                    "变动方向": "增持" if diff > 0 else "减持",
                                    "变动幅度(%)": abs(diff),
                                }
                            )
                    except Exception:
                        continue
                result["股东增减持"] = {
                    "对比期": f"{dates[1]} → {dates[0]}",
                    "变动记录": changes,
                }
        return result
    except Exception as e:
        return {"股票代码": stock_code, "error": str(e)}
