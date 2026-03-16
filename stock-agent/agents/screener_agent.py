"""
Agent 2 — 企业精筛（开盘后运行）

从 Agent 1 的受益行业/公司出发，对候选股票进行 6 维度评分，输出 Top 20。

6 维度评分（每项 0-3 分，满分 18 分）：
  D1 行业龙头    — 复用 run_industry_leader_analysis()        [LLM]
  D2 受益程度    — 轻量 LLM（max_tokens=200）                 [LLM]
  D3 股东结构    — 复用 run_shareholder_analysis()            [LLM]
  D4 中长期趋势  — 复用 run_trend_analysis()                  [LLM]
  D5 技术量能    — Python 规则：近3日均量 vs 20日均量         [0 token]
  D6 估值合理性  — Python 规则：60日价格波动率 < 15%          [0 token]
"""

import asyncio
import json
import os
import re
from datetime import datetime
from typing import Any, Optional

import akshare as ak
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agents.industry_leader_agent import run_industry_leader_analysis
from agents.shareholder_agent import run_shareholder_analysis
from agents.trend_agent import run_trend_analysis
from config.settings import settings
from tools.technical_indicators import _calc_volume_analysis, _get_kline_data


SCREENER_D2_SYSTEM_PROMPT = """你是A股行业分析师，请评估该股票从本次事件中的受益程度。

评分标准（0-3分）：
3分 — 直接、核心受益方（业务与事件高度相关，营收/利润直接提升）
2分 — 间接受益（产业链相关，但受益有时滞）
1分 — 边缘受益（同行业但关联度低）
0分 — 无明显受益

只输出JSON：{"d2_score": <0-3>, "reason": "<30字内原因>"}"""


SCREENER_RECOMMEND_SYSTEM_PROMPT = """你是A股专业分析师，请根据股票的6维度评分生成投资推荐摘要。

请输出JSON：
{
  "recommendation": "<50字内推荐理由>",
  "risk_warning": "<30字内风险提示>",
  "suggested_action": "积极关注/谨慎关注/观望"
}"""


async def _get_candidate_stocks(
    affected_industries: list[str],
    affected_companies: list[str],
) -> list[dict[str, Any]]:
    """
    从受益行业和公司名称中构建候选股票列表

    策略：
    1. 具名公司直接搜索代码
    2. 从全市场行情中按行业过滤
    """
    candidates: dict[str, dict] = {}  # code -> stock_info

    # 获取全市场行情（一次调用，后续复用）
    try:
        spot_df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
    except Exception:
        spot_df = pd.DataFrame()

    # 1. 按行业过滤
    if not spot_df.empty and affected_industries:
        for industry in affected_industries:
            try:
                board_df = await asyncio.to_thread(
                    ak.stock_board_industry_cons_em, symbol=industry
                )
                if board_df is None or board_df.empty:
                    continue
                # 按总市值排序，取前30名（龙头优先）
                if "总市值" in board_df.columns:
                    board_df["总市值"] = pd.to_numeric(board_df["总市值"], errors="coerce")
                    board_df = board_df.sort_values("总市值", ascending=False)
                for _, row in board_df.head(30).iterrows():
                    code = str(row.get("代码", "")).zfill(6)
                    name = str(row.get("名称", ""))
                    if code and "ST" not in name and "退" not in name:
                        if code not in candidates:
                            candidates[code] = {
                                "代码": code,
                                "名称": name,
                                "来源": f"行业:{industry}",
                            }
            except Exception:
                pass

    # 2. 按公司名搜索（名称模糊匹配）
    if not spot_df.empty and affected_companies:
        for company_name in affected_companies:
            # 从全市场行情中模糊匹配公司名
            short_name = company_name[:4]  # 取前4字符做模糊匹配
            if "名称" in spot_df.columns:
                matched = spot_df[spot_df["名称"].str.contains(short_name, na=False)]
                for _, row in matched.head(3).iterrows():
                    code = str(row.get("代码", "")).zfill(6)
                    name = str(row.get("名称", ""))
                    if code and "ST" not in name:
                        if code not in candidates:
                            candidates[code] = {
                                "代码": code,
                                "名称": name,
                                "来源": f"具名公司:{company_name}",
                            }

    # 过滤：排除 ST/退/科创板50以下小票
    result = []
    for code, info in candidates.items():
        name = info["名称"]
        if "ST" in name or "退" in name:
            continue
        # 补充市值信息
        if not spot_df.empty and "代码" in spot_df.columns:
            row = spot_df[spot_df["代码"] == code]
            if not row.empty:
                info["流通市值"] = float(row.iloc[0].get("流通市值", 0) or 0)
                info["总市值"] = float(row.iloc[0].get("总市值", 0) or 0)
                info["涨跌幅"] = float(row.iloc[0].get("涨跌幅", 0) or 0)
        result.append(info)

    # 按总市值降序（龙头优先进入分析）
    result.sort(key=lambda x: x.get("总市值", 0), reverse=True)
    return result[:60]  # 最多60个候选，避免LLM调用过多


def _score_d5_volume(stock_code: str) -> tuple[int, str]:
    """
    D5 技术量能评分（Python规则）

    规则：近3日均量 vs 20日均量
    - 5倍以上 → 3分（放量突破）
    - 2-5倍   → 2分（量能放大）
    - 1-2倍   → 1分（正常量能）
    - 低于均量 → 0分（缩量）
    """
    try:
        df = _get_kline_data(stock_code, days=60)
        if df is None or df.empty or "volume" not in df.columns:
            return 1, "数据不足，默认1分"

        volume = df["volume"].dropna()
        if len(volume) < 20:
            return 1, "数据不足，默认1分"

        ma3 = float(volume.tail(3).mean())
        ma20 = float(volume.rolling(20).mean().iloc[-1])

        if ma20 <= 0:
            return 1, "均量为0，默认1分"

        ratio = ma3 / ma20

        if ratio >= 5.0:
            return 3, f"近3日均量是20日均量的{ratio:.1f}倍，强烈放量"
        elif ratio >= 2.0:
            return 2, f"近3日均量是20日均量的{ratio:.1f}倍，量能放大"
        elif ratio >= 1.0:
            return 1, f"近3日均量是20日均量的{ratio:.1f}倍，量能正常"
        else:
            return 0, f"近3日均量是20日均量的{ratio:.1f}倍，缩量"
    except Exception as e:
        return 1, f"计算失败，默认1分: {str(e)[:50]}"


def _score_d6_valuation_stability(stock_code: str) -> tuple[int, str]:
    """
    D6 估值合理性评分（Python规则）

    规则：60日收盘价波动率（年化标准差）
    - <15%  → 3分（低波动，估值稳定）
    - 15-30% → 2分（中等波动）
    - 30-50% → 1分（较高波动）
    - >50%  → 0分（高度投机）
    """
    try:
        df = _get_kline_data(stock_code, days=90)
        if df is None or df.empty or "close" not in df.columns:
            return 1, "数据不足，默认1分"

        close = df["close"].dropna().tail(60)
        if len(close) < 20:
            return 1, "数据不足，默认1分"

        # 计算日收益率标准差，年化
        daily_returns = close.pct_change().dropna()
        vol_daily = float(daily_returns.std())
        vol_annual = vol_daily * (252 ** 0.5) * 100  # 转为百分比

        if vol_annual < 15:
            return 3, f"60日年化波动率{vol_annual:.1f}%，估值稳定"
        elif vol_annual < 30:
            return 2, f"60日年化波动率{vol_annual:.1f}%，波动适中"
        elif vol_annual < 50:
            return 1, f"60日年化波动率{vol_annual:.1f}%，波动较大"
        else:
            return 0, f"60日年化波动率{vol_annual:.1f}%，高度投机"
    except Exception as e:
        return 1, f"计算失败，默认1分: {str(e)[:50]}"


async def _score_d2_benefit(
    stock_code: str,
    stock_name: str,
    trigger_summary: str,
    llm: ChatOpenAI,
) -> tuple[int, str]:
    """D2 受益程度：轻量 LLM 评分"""
    try:
        msg = f"股票：{stock_name}（{stock_code}）\n触发事件：{trigger_summary}\n请评分。"
        response = await llm.ainvoke([
            SystemMessage(content=SCREENER_D2_SYSTEM_PROMPT),
            HumanMessage(content=msg),
        ])
        result = json.loads(re.search(r'\{[\s\S]*\}', response.content).group())
        return int(result.get("d2_score", 1)), result.get("reason", "")
    except Exception:
        return 1, "评分失败，默认1分"


async def _score_single_stock(
    stock: dict[str, Any],
    trigger_summary: str,
    llm: ChatOpenAI,
    semaphore: asyncio.Semaphore,
) -> Optional[dict[str, Any]]:
    """对单只股票执行6维度评分"""
    code = stock["代码"]
    name = stock["名称"]

    async with semaphore:
        print(f"    → 评分 {code} {name}...")

        # D5/D6 同步执行（无IO）
        d5_score, d5_reason = _score_d5_volume(code)
        d6_score, d6_reason = _score_d6_valuation_stability(code)

        # D1/D3/D4 并行（LLM + akshare）
        d1_task = run_industry_leader_analysis(code)
        d3_task = run_shareholder_analysis(code)
        d4_task = run_trend_analysis(code)
        d2_task = _score_d2_benefit(code, name, trigger_summary, llm)

        try:
            d1_result, d3_result, d4_result, (d2_score, d2_reason) = await asyncio.gather(
                d1_task, d3_task, d4_task, d2_task,
                return_exceptions=True,
            )
        except Exception as e:
            return None

        # 提取评分（原始分0-100 → 映射到0-3）
        def map_to_3(raw_score: float) -> int:
            """将0-100分映射到0-3"""
            if raw_score >= 75:
                return 3
            elif raw_score >= 55:
                return 2
            elif raw_score >= 35:
                return 1
            else:
                return 0

        if isinstance(d1_result, Exception):
            d1_score = 1
        else:
            d1_score = map_to_3(float(d1_result.get("score", 50)))

        if isinstance(d3_result, Exception):
            d3_score = 1
        else:
            d3_score = map_to_3(float(d3_result.get("score", 50)))

        if isinstance(d4_result, Exception):
            d4_score = 1
        else:
            d4_score = map_to_3(float(d4_result.get("score", 50)))

        total_score = d1_score + d2_score + d3_score + d4_score + d5_score + d6_score

        # 生成推荐理由
        try:
            score_summary = (
                f"D1龙头:{d1_score} D2受益:{d2_score} D3股东:{d3_score} "
                f"D4趋势:{d4_score} D5量能:{d5_score} D6估值:{d6_score} 总分:{total_score}/18"
            )
            rec_msg = f"股票：{name}（{code}）\n评分：{score_summary}\n触发事件：{trigger_summary}"
            rec_resp = await llm.ainvoke([
                SystemMessage(content=SCREENER_RECOMMEND_SYSTEM_PROMPT),
                HumanMessage(content=rec_msg),
            ])
            rec_json = json.loads(re.search(r'\{[\s\S]*\}', rec_resp.content).group())
            recommendation = rec_json.get("recommendation", "")
            risk_warning = rec_json.get("risk_warning", "")
            suggested_action = rec_json.get("suggested_action", "观望")
        except Exception:
            recommendation = d2_reason
            risk_warning = ""
            suggested_action = "观望"

        return {
            "代码": code,
            "名称": name,
            "来源": stock.get("来源", ""),
            "总分": total_score,
            "维度得分": {
                "D1_行业龙头": d1_score,
                "D2_受益程度": d2_score,
                "D3_股东结构": d3_score,
                "D4_中长期趋势": d4_score,
                "D5_技术量能": d5_score,
                "D6_估值合理性": d6_score,
            },
            "维度说明": {
                "D2": d2_reason,
                "D5": d5_reason,
                "D6": d6_reason,
            },
            "推荐理由": recommendation,
            "风险提示": risk_warning,
            "建议操作": suggested_action,
            "市值(亿)": round(stock.get("总市值", 0) / 1e8, 1),
            "今日涨跌幅": stock.get("涨跌幅", 0),
        }


async def run_screener_agent(trigger_result: dict[str, Any]) -> dict[str, Any]:
    """
    执行 Agent 2：企业精筛

    Args:
        trigger_result: Agent 1 的 TriggerResult 输出

    Returns:
        {
            "top20": list[dict],         # 按总分排序的前20只股票
            "total_candidates": int,
            "date": str,
            "trigger_summary": str,
        }
    """
    print("\n[Agent 2] 开始企业精筛...")
    date_str = datetime.now().strftime("%Y-%m-%d")

    if not trigger_result.get("triggered"):
        print("  → Agent 1 未触发，跳过精筛")
        return {
            "top20": [],
            "total_candidates": 0,
            "date": date_str,
            "trigger_summary": trigger_result.get("trigger_summary", ""),
        }

    affected_industries = trigger_result.get("affected_industries", [])
    affected_companies = trigger_result.get("affected_companies", [])
    trigger_summary = trigger_result.get("trigger_summary", "")

    # ── Step 1: 获取候选股票 ──────────────────────────────────
    print(f"  [Step 1] 构建候选股票池（行业:{affected_industries}，公司:{affected_companies}）...")
    candidates = await _get_candidate_stocks(affected_industries, affected_companies)
    print(f"  → 候选股票 {len(candidates)} 只")

    if not candidates:
        return {
            "top20": [],
            "total_candidates": 0,
            "date": date_str,
            "trigger_summary": trigger_summary,
        }

    # ── Step 2: 6维度并发评分 ────────────────────────────────
    print(f"  [Step 2] 开始 6 维度评分（并发3，共 {len(candidates)} 只）...")
    semaphore = asyncio.Semaphore(3)
    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=0.1,
        max_tokens=200,
    )

    tasks = [
        _score_single_stock(stock, trigger_summary, llm, semaphore)
        for stock in candidates
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    scored = [r for r in results if isinstance(r, dict) and r is not None]

    # ── Step 3: 排序，输出 Top 20 ─────────────────────────────
    scored.sort(key=lambda x: x["总分"], reverse=True)
    top20 = scored[:20]

    print(f"  → 评分完成，Top 3：")
    for s in top20[:3]:
        print(f"     {s['代码']} {s['名称']} 总分{s['总分']}/18 — {s['推荐理由'][:30]}")

    screener_result = {
        "top20": top20,
        "total_candidates": len(candidates),
        "scored_count": len(scored),
        "date": date_str,
        "trigger_summary": trigger_summary,
    }

    # ── Step 4: 持久化到 data/daily_push/ ───────────────────
    _save_daily_push(screener_result)

    return screener_result


def _save_daily_push(screener_result: dict[str, Any]) -> None:
    """将每日推送结果保存到 data/daily_push/{date}.json"""
    date_str = screener_result["date"]
    save_dir = os.path.join(os.path.dirname(__file__), "..", "data", "daily_push")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{date_str}.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(screener_result, f, ensure_ascii=False, indent=2, default=str)
    print(f"  → 推送记录已保存：{save_path}")
