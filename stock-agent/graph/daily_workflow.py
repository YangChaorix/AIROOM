"""
每日自动选股工作流

流程：
  [Python] Step 1: 获取今日涨幅前50
  [Python] Step 2: 基础过滤（ST/涨停/换手率/市值）
  [Python] Step 3: 异步获取行业 + 新闻关键词匹配打分
  [LLM×1 ] Step 4: AI预筛选 Top10
  [LLM×N ] Step 5: 对Top10跑完整7维度分析
           Step 6: 输出排名报告
"""

import asyncio
from datetime import datetime
from typing import Any

from agents.news_scanner_agent import (
    extract_hot_industries,
    fetch_todays_news,
    score_stocks_by_news,
)
from agents.stock_picker_agent import run_stock_picker
from graph.workflow import run_batch_analysis
from tools.market_screener import basic_filter, enrich_with_industry, get_top_gainers


async def run_daily_scan(
    top_n_gainers: int = 50,
    final_top_n: int = 10,
    max_concurrent: int = 2,
) -> dict[str, Any]:
    """
    执行每日自动选股全流程

    Args:
        top_n_gainers: 从涨幅前N开始筛选
        final_top_n:   最终进入7维度分析的股票数
        max_concurrent: 7维度分析最大并发数

    Returns:
        完整结果字典
    """
    start_time = datetime.now()
    date_str = start_time.strftime("%Y-%m-%d")
    print(f"\n{'='*60}")
    print(f"每日自动选股  {date_str}")
    print(f"{'='*60}")

    # ── Step 1: 获取今日涨幅榜 ──────────────────────────────────
    print(f"\n[Step 1] 获取今日A股涨幅前 {top_n_gainers} 名...")
    raw_gainers = get_top_gainers(top_n_gainers)
    print(f"  → 获取到 {len(raw_gainers)} 只")

    # ── Step 2: Python基础过滤 ──────────────────────────────────
    print("\n[Step 2] Python规则过滤（排除ST/涨停/高换手/小市值）...")
    filtered = basic_filter(raw_gainers)
    print(f"  → 过滤后剩余 {len(filtered)} 只")
    if not filtered:
        print("  候选股票为空，终止流程")
        return {"date": date_str, "error": "过滤后无候选股票", "is_complete": False}

    # ── Step 3: 行业信息 + 新闻关键词匹配 ─────────────────────
    print("\n[Step 3] 并行获取行业信息 + 拉取今日新闻...")
    enriched_task = enrich_with_industry(filtered)
    news_task = asyncio.to_thread(fetch_todays_news)
    enriched, news_data = await asyncio.gather(enriched_task, news_task)

    hot_industries = extract_hot_industries(news_data["titles"])
    print(f"  → 今日热点行业：{list(hot_industries.keys()) or '无明确命中'}")

    scored = score_stocks_by_news(enriched, hot_industries)
    print(f"  → 综合初筛分排名前5：")
    for s in scored[:5]:
        hits = "/".join(s.get("命中新闻", [])) or "无"
        print(f"     {s['代码']} {s['名称']} | {s.get('行业','?')} | "
              f"涨幅{s['涨跌幅']}% | 新闻:{hits} | 初筛分:{s['综合初筛分']}")

    # ── Step 4: LLM轻量预筛选 ──────────────────────────────────
    print(f"\n[Step 4] AI预筛选 Top{final_top_n}（1次LLM调用）...")
    top_codes = await run_stock_picker(scored, news_data["summary"], top_n=final_top_n)
    if not top_codes:
        print("  AI预筛选无输出，使用初筛分前N兜底")
        top_codes = [s["代码"] for s in scored[:final_top_n]]
    print(f"  → 进入深度分析：{top_codes}")

    # ── Step 5: 7维度完整分析 ───────────────────────────────────
    print(f"\n[Step 5] 对 {len(top_codes)} 只股票进行7维度分析（并发{max_concurrent}）...")
    analysis_results = await run_batch_analysis(top_codes, max_concurrent=max_concurrent)

    elapsed = (datetime.now() - start_time).seconds
    print(f"\n{'='*60}")
    print(f"每日选股完成，耗时 {elapsed}s")
    print(f"{'='*60}\n")

    return {
        "date": date_str,
        "raw_gainers_count": len(raw_gainers),
        "filtered_count": len(filtered),
        "hot_industries": hot_industries,
        "top_codes": top_codes,
        "analysis_results": analysis_results,
        "is_complete": True,
    }
