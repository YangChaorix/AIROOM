"""
市场行情工具：涨跌幅榜，供 review_agent 复盘使用
"""

import tools.proxy_patch  # noqa: F401 — 修复 Clash Fake-IP 模式下 requests 走系统代理的问题
from datetime import datetime
from typing import Any

import akshare as ak
import pandas as pd


def get_market_movers(top_n: int = 50) -> dict[str, Any]:
    """
    获取当日A股涨停板/跌停板及市场概况，供复盘分析使用。
    使用 datacenter-web.eastmoney.com（稳定）替代 push2.eastmoney.com（不稳定）。
    """
    today = datetime.now().strftime("%Y%m%d")
    result = {
        "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "涨幅前50": [],
        "跌幅前50": [],
        "市场概况": {},
    }

    # ── 涨停板 ──────────────────────────────────────────
    try:
        df = ak.stock_zt_pool_em(date=today)
        if df is not None and not df.empty:
            df = df[~df["名称"].str.contains("ST|退", na=False)]
            for _, row in df.head(top_n).iterrows():
                result["涨幅前50"].append({
                    "代码": str(row.get("代码", "")).zfill(6),
                    "名称": str(row.get("名称", "")),
                    "最新价": float(row.get("最新价", 0) or 0),
                    "涨跌幅(%)": float(row.get("涨跌幅", 0) or 0),
                    "换手率(%)": float(row.get("换手率", 0) or 0),
                    "成交额(亿)": round(float(row.get("成交额", 0) or 0) / 1e8, 2),
                    "连板数": int(row.get("连板数", 1) or 1),
                    "所属行业": str(row.get("所属行业", "")),
                })
    except Exception as e:
        result["涨停板_error"] = str(e)

    # ── 跌停板 ──────────────────────────────────────────
    try:
        df2 = ak.stock_zt_pool_dtgc_em(date=today)
        if df2 is not None and not df2.empty:
            df2 = df2[~df2["名称"].str.contains("ST|退", na=False)]
            for _, row in df2.head(top_n).iterrows():
                result["跌幅前50"].append({
                    "代码": str(row.get("代码", "")).zfill(6),
                    "名称": str(row.get("名称", "")),
                    "最新价": float(row.get("最新价", 0) or 0),
                    "涨跌幅(%)": float(row.get("涨跌幅", 0) or 0),
                    "换手率(%)": float(row.get("换手率", 0) or 0),
                })
    except Exception as e:
        result["跌停板_error"] = str(e)

    # ── 市场概况（乐咕乐股，稳定） ──────────────────────
    try:
        legu = ak.stock_market_activity_legu()
        if legu is not None and not legu.empty:
            legu_dict = dict(zip(legu["item"], legu["value"]))
            up = int(legu_dict.get("上涨", 0) or 0)
            down = int(legu_dict.get("下跌", 0) or 0)
            zt = int(legu_dict.get("涨停", 0) or 0)
            dt = int(legu_dict.get("跌停", 0) or 0)
            total = up + down
            avg_pct = (up - down) / total * 100 if total > 0 else 0
            result["市场概况"] = {
                "上涨家数": up,
                "下跌家数": down,
                "涨停家数": zt,
                "跌停家数": dt,
                "平均涨跌幅(%)": round(avg_pct, 2),
                "市场情绪": "偏强" if avg_pct > 5 else ("偏弱" if avg_pct < -5 else "中性"),
            }
    except Exception as e:
        result["市场概况_error"] = str(e)

    return result


def get_sector_performance() -> list[dict]:
    """
    获取板块涨跌幅（行业板块）
    """
    try:
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.iterrows():
            result.append(
                {
                    "板块名称": str(row.get("板块名称", "")),
                    "涨跌幅(%)": float(row.get("涨跌幅", 0) or 0),
                    "涨跌额": float(row.get("涨跌额", 0) or 0),
                    "总市值(亿)": round(float(row.get("总市值", 0) or 0) / 1e8, 2),
                }
            )
        result.sort(key=lambda x: x["涨跌幅(%)"], reverse=True)
        return result
    except Exception:
        return []
