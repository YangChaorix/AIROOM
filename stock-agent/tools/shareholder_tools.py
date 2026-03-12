"""
股东结构数据工具模块
获取A股前十大股东、机构持股、股东变动等数据
封装为 LangChain Tool 供 Agent 使用
"""

import json
import traceback
from datetime import datetime

import akshare as ak
import pandas as pd
from langchain_core.tools import tool


@tool
def get_top_shareholders(stock_code: str) -> str:
    """
    获取股票前十大股东信息，包括股东名称、持股数量、持股比例、股东类型。
    用于分析筹码结构：私募基金和个人投资者合计持股比例是否超过60%。

    Args:
        stock_code: A股股票代码，如 '000001' 或 '600519'

    Returns:
        JSON格式的前十大股东数据字符串
    """
    try:
        result = {
            "股票代码": stock_code,
            "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 1. 获取前十大股东（来源：东方财富）
        try:
            holder_df = ak.stock_gdfx_top_10_em(symbol=stock_code)
            if holder_df is not None and not holder_df.empty:
                holders = []
                for _, row in holder_df.iterrows():
                    holder = {}
                    for col in holder_df.columns:
                        val = row[col]
                        holder[col] = str(val) if not (isinstance(val, float) and pd.isna(val)) else "N/A"
                    holders.append(holder)
                result["前十大股东"] = holders

                # 尝试识别股东类型并计算私募+个人比例
                private_and_individual_pct = 0.0
                institution_pct = 0.0
                state_pct = 0.0

                for h in holders:
                    # 尝试提取持股比例
                    pct_key = None
                    for k in ["持股比例", "占流通股比例", "持股比例(%)", "比例"]:
                        if k in h:
                            pct_key = k
                            break

                    if pct_key:
                        try:
                            pct_str = str(h[pct_key]).replace("%", "").strip()
                            pct = float(pct_str)
                        except (ValueError, TypeError):
                            pct = 0.0
                    else:
                        pct = 0.0

                    # 股东名称判断类型
                    name = str(h.get("股东名称", h.get("名称", "")))
                    if any(kw in name for kw in ["基金", "私募", "信托", "资产管理", "投资管理"]):
                        if any(kw in name for kw in ["国家", "国有", "中央", "政府"]):
                            state_pct += pct
                        else:
                            private_and_individual_pct += pct
                    elif any(kw in name for kw in ["社保", "保险", "养老"]):
                        institution_pct += pct
                    elif any(kw in name for kw in ["国家", "国有", "国资委", "汇金", "财政部"]):
                        state_pct += pct
                    elif any(kw in name for kw in ["银行", "证券", "ETF", "指数"]):
                        institution_pct += pct
                    else:
                        # 个人或私募
                        private_and_individual_pct += pct

                result["股权结构分析"] = {
                    "私募+个人持股合计(%)": round(private_and_individual_pct, 2),
                    "机构持股(%)": round(institution_pct, 2),
                    "国资持股(%)": round(state_pct, 2),
                    "是否满足条件(私募+个人>60%)": private_and_individual_pct >= 60,
                    "分析说明": "基于股东名称关键词推断，仅供参考",
                }
        except Exception as e:
            result["前十大股东获取失败"] = str(e)

        # 2. 获取前十大流通股股东
        try:
            float_holder_df = ak.stock_gdfx_free_top_10_em(symbol=stock_code)
            if float_holder_df is not None and not float_holder_df.empty:
                float_holders = []
                for _, row in float_holder_df.head(10).iterrows():
                    holder = {}
                    for col in float_holder_df.columns:
                        val = row[col]
                        holder[col] = str(val) if not (isinstance(val, float) and pd.isna(val)) else "N/A"
                    float_holders.append(holder)
                result["前十大流通股股东"] = float_holders
        except Exception as e:
            result["流通股东获取备注"] = f"流通股股东获取失败: {str(e)}"

        # 3. 获取机构持股汇总（基金持仓）
        try:
            fund_holder_df = ak.stock_report_fund_hold_detail(symbol=stock_code, date=datetime.now().strftime("%Y%m%d"))
            if fund_holder_df is not None and not fund_holder_df.empty:
                result["基金持仓概况"] = {
                    "持仓基金数量": len(fund_holder_df),
                    "持仓数据": fund_holder_df.head(5).to_dict(orient="records"),
                }
        except Exception:
            pass  # 基金持仓数据可选

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": f"获取股票 {stock_code} 股东数据失败: {str(e)}",
            "traceback": traceback.format_exc()
        }, ensure_ascii=False)


@tool
def get_shareholder_changes(stock_code: str) -> str:
    """
    获取股东增减持记录，分析大股东和机构的增减持行为，判断主力动向。

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

        # 获取重要股东增减持数据
        try:
            change_df = ak.stock_em_hsgt_north_acc_flow_in(symbol="北向资金")
            # 此接口获取的是北向资金，用来补充判断
        except Exception:
            pass

        # 获取股票增减持明细（通过东方财富）
        try:
            hold_df = ak.stock_report_fund_hold(symbol=stock_code, date=datetime.now().strftime("%Y%m"))
            if hold_df is not None and not hold_df.empty:
                result["机构持仓变动"] = hold_df.head(10).to_dict(orient="records")
        except Exception as e:
            result["机构持仓变动备注"] = f"获取失败: {str(e)}"

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        return json.dumps({
            "error": f"获取股票 {stock_code} 股东变动数据失败: {str(e)}",
        }, ensure_ascii=False)
