"""
股东结构数据工具模块
获取A股前十大流通股股东、股东变动等数据
封装为 LangChain Tool 供 Agent 使用
"""

import json
import traceback
from datetime import datetime

import akshare as ak
import pandas as pd
from langchain_core.tools import tool


def _classify_holder(name: str, nature: str = "") -> str:
    """
    根据股东名称和股本性质判断类型
    nature: 股本性质字段值（优先使用）
    """
    name = str(name)
    nature = str(nature)

    # 优先用股本性质字段判断
    if "国有股" in nature or "国家股" in nature:
        return "国资"
    if "境外" in nature or "HKSCC" in name or "香港中央" in name:
        return "外资/北向"

    # 名称关键词判断
    if any(kw in name for kw in ["社保", "保险", "养老", "全国社保"]):
        return "社保/保险"
    if any(kw in name for kw in ["中央汇金", "汇金", "财政部", "国资委",
                                   "省国有资本", "省财政", "国有资本运营",
                                   "国家队", "诚通", "中国国新"]):
        return "国资"
    if any(kw in name for kw in ["证券投资基金", "ETF", "指数基金", "华夏基金",
                                   "易方达", "南方基金", "嘉实", "博时", "富国",
                                   "招商基金", "广发基金", "工银瑞信", "汇添富"]):
        return "公募基金"
    if any(kw in name for kw in ["证券", "银行", "信托"]) and "基金" not in name:
        return "银行/证券/信托"
    if any(kw in name for kw in ["私募", "投资管理", "资产管理", "合伙企业"]):
        return "私募/资管"
    # 集团/有限公司类（排除上面已判断的）但包含国字头
    if any(kw in name for kw in ["国家", "国有", "国资", "中央", "政府"]):
        return "国资"
    # 个人：纯中文姓名（2-4个汉字，无公司后缀）
    stripped = name.strip()
    if 2 <= len(stripped) <= 5 and all('\u4e00' <= c <= '\u9fff' for c in stripped):
        return "个人"
    return "其他机构"


@tool
def get_top_shareholders(stock_code: str) -> str:
    """
    获取股票前十大流通股股东信息，分析筹码结构。
    重点判断：私募基金和个人投资者持股合计是否超过60%。

    Args:
        stock_code: A股股票代码，如 '000001' 或 '600519'

    Returns:
        JSON格式的前十大股东数据字符串，含筹码结构分析
    """
    try:
        result = {
            "股票代码": stock_code,
            "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 1. 前十大流通股股东（stock_circulate_stock_holder）
        try:
            df = ak.stock_circulate_stock_holder(symbol=stock_code)
            if df is not None and not df.empty:
                # 取最新一期（截止日期最大的）
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

                    holders.append({
                        "股东名称": name,
                        "持股数量": str(row.get("持股数量", "N/A")),
                        "占流通股比例(%)": pct,
                        "股本性质": str(row.get("股本性质", "N/A")),
                        "股东类型(推断)": h_type,
                    })

                result["前十大流通股股东"] = holders

                # 汇总筹码结构
                private_pct = type_stats.get("私募/资管", 0) + type_stats.get("个人", 0) + type_stats.get("其他机构", 0)
                state_pct = type_stats.get("国资", 0)
                fund_pct = type_stats.get("公募基金", 0)
                social_pct = type_stats.get("社保/保险", 0)
                foreign_pct = type_stats.get("外资/北向", 0)
                bank_pct = type_stats.get("银行/证券/信托", 0)

                result["筹码结构分析"] = {
                    "数据期": str(result.get("数据截止日期", "未知")),
                    "私募+个人持股(%)": round(private_pct, 2),
                    "国资持股(%)": round(state_pct, 2),
                    "公募基金持股(%)": round(fund_pct, 2),
                    "社保/保险持股(%)": round(social_pct, 2),
                    "外资北向持股(%)": round(foreign_pct, 2),
                    "银行/证券/信托持股(%)": round(bank_pct, 2),
                    "前十合计持股(%)": round(sum(type_stats.values()), 2),
                    "是否满足私募+个人>60%": private_pct >= 60,
                    "各类型明细": {k: round(v, 2) for k, v in type_stats.items()},
                }
        except Exception as e:
            result["前十大股东获取失败"] = str(e)

        # 2. 基金持仓（公募基金）
        try:
            fund_df = ak.stock_fund_stock_holder(symbol=stock_code)
            if fund_df is not None and not fund_df.empty:
                result["公募基金持仓"] = {
                    "持仓基金数量": len(fund_df),
                    "最新数据": fund_df.head(5).to_dict(orient="records"),
                }
        except Exception:
            pass

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": f"获取股票 {stock_code} 股东数据失败: {str(e)}",
            "traceback": traceback.format_exc()
        }, ensure_ascii=False)


@tool
def get_shareholder_changes(stock_code: str) -> str:
    """
    获取股东增减持记录，分析主要股东行为。

    Args:
        stock_code: A股股票代码，如 '000001' 或 '600519'

    Returns:
        JSON格式的股东增减持数据字符串
    """
    try:
        result = {
            "股票代码": stock_code,
            "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 主要股东变动（比较最近两期）
        try:
            df = ak.stock_circulate_stock_holder(symbol=stock_code)
            if df is not None and not df.empty and "截止日期" in df.columns:
                dates = sorted(df["截止日期"].unique(), reverse=True)
                if len(dates) >= 2:
                    latest = df[df["截止日期"] == dates[0]][["股东名称", "占流通股比例"]].set_index("股东名称")
                    prev = df[df["截止日期"] == dates[1]][["股东名称", "占流通股比例"]].set_index("股东名称")
                    changes = []
                    for name in set(list(latest.index) + list(prev.index)):
                        cur_pct = float(str(latest.loc[name, "占流通股比例"]).replace("%", "")) if name in latest.index else 0
                        pre_pct = float(str(prev.loc[name, "占流通股比例"]).replace("%", "")) if name in prev.index else 0
                        diff = round(cur_pct - pre_pct, 3)
                        if diff != 0:
                            changes.append({"股东名称": name, "变动方向": "增持" if diff > 0 else "减持", "变动幅度(%)": abs(diff)})
                    result["股东增减持"] = {
                        "对比期": f"{dates[1]} → {dates[0]}",
                        "变动记录": changes,
                    }
        except Exception as e:
            result["股东变动备注"] = f"对比分析失败: {str(e)}"

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": f"获取股东变动失败: {str(e)}",
        }, ensure_ascii=False)
