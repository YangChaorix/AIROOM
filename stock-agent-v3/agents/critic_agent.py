"""
Agent 4：批评 Agent（Critic Agent）
收盘后（15:40）对当日精筛推荐进行绩效验证，分析各维度预测准确性，
自动生成改进版精筛 Prompt 并激活，同时保留回滚能力。
"""

import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── 默认系统提示词（首次运行时作为种子写入 DB） ────────────────────────────

# ── 可编辑部分（Critic 自身提示词，可迭代） ──────────────────────────────────
_CRITIC_EDITABLE = """你是一个A股选股系统的批评分析师。你会收到今日精筛Agent推荐的股票列表，以及这些股票当日实际的开盘→收盘涨跌幅数据。

**你的任务分两部分，必须按格式输出：**

━━━ 第一部分：批评报告（Markdown） ━━━

# 选股批评报告 - {date}

## 1. 今日概况
- 推荐 {total} 只，跑赢大盘（市场均值 {market_avg:.2f}%）{beat_count} 只，胜率 {win_rate:.0f}%
- 推荐平均收益：{avg_return:.2f}%，大盘均值：{market_avg:.2f}%，超额：{excess:.2f}%

## 2. 表现排行
### Top 5 最佳推荐
（从表现最好的5只中分析：推荐理由与实际结果是否吻合，哪个维度判断最准确）

### Bottom 5 最差推荐
（从表现最差的5只中分析：哪个维度判断失误，根因是什么）

## 3. 维度准确性分析
| 维度 | 高分股（≥2分）跑赢大盘比例 | 低分股（0-1分）跑赢大盘比例 | 预测价值 |
|------|--------------------------|--------------------------|---------|
| D1 行业龙头地位 | X% | X% | 高/中/低 |
| D2 主营产品受益 | X% | X% | 高/中/低 |
| D3 股东结构    | X% | X% | 高/中/低 |
| D4 上涨趋势    | X% | X% | 高/中/低 |
| D5 技术突破    | X% | X% | 高/中/低 |
| D6 估值合理    | X% | X% | 高/中/低 |

## 4. 系统性偏差
（描述本次推荐中存在的固定错误模式，如：过度偏向某类行业、特定维度系统性高估等）

## 5. 具体改进建议
（至少3条，格式：**问题**：...  **建议**：...）"""

# ── 固定输出格式（含哨兵分隔符，后端解析依赖，不可修改） ───────────────────
_CRITIC_OUTPUT_FORMAT = """━━━ 第二部分：改进后的精筛Prompt ━━━
在下方分隔符后，输出改进版精筛System Prompt的**可编辑部分**。

**重要约束（必须遵守）：**
1. 保持D1-D6六个维度的结构不变（只改各维度的评分标准文字）
2. 只输出精筛Prompt的可编辑分析准则部分，JSON格式模板由系统自动附加（不要在建议中包含JSON格式）
3. 保持0-3分制不变
4. 改进内容仅限于：维度的评分标准描述、注意事项、典型案例说明
5. 不得新增或删除维度，不得修改维度名称（D1_龙头地位等）

---SUGGESTED_PROMPT_BELOW---
（此处只输出精筛Prompt的可编辑分析准则部分，不包含JSON格式模板，系统会自动追加）"""

# 完整提示词（代码常量后备，运行时以 DB 为准）
CRITIC_SYSTEM_PROMPT = _CRITIC_EDITABLE + "\n\n" + _CRITIC_OUTPUT_FORMAT


def _get_today_kline(stock_code: str) -> Optional[dict]:
    """获取今日 open/close/pct_change，失败返回 None"""
    try:
        from tools.technical_tools import _get_kline
        df = _get_kline(stock_code, days=5)
        if df is None or df.empty:
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        row = df[df["date"].astype(str).str.startswith(today)]
        if row.empty:
            # 尝试最新一行（可能是昨日数据）
            row = df.tail(1)
        r = row.iloc[-1]
        return {
            "open": float(r.get("open", 0) or 0),
            "close": float(r.get("close", 0) or 0),
            "pct_change": float(r.get("pct_change", 0) or 0),
        }
    except Exception as e:
        logger.debug(f"[{stock_code}] K线获取失败: {e}")
        return None


def _get_market_avg() -> float:
    """获取今日市场平均涨跌幅（用沪深300近似）"""
    try:
        from tools.market_screener import get_market_movers
        data = get_market_movers(top_n=50)
        overview = data.get("市场概况", {})
        avg = overview.get("avg_pct_change") or overview.get("平均涨跌幅")
        if avg is not None:
            return float(avg)
    except Exception as e:
        logger.debug(f"市场均值获取失败: {e}")
    return 0.0


def _build_performance_table(stocks: list, market_avg: float) -> list:
    """为每只推荐股抓取当日价格，计算相对大盘表现"""
    results = []
    for s in stocks:
        code = s.get("stock_code") or s.get("code", "")
        name = s.get("stock_name") or s.get("name", "")
        kline = _get_today_kline(code) if code else None
        if kline and kline["open"] and kline["close"]:
            # 使用 pct_change（收盘/昨收-1），与交易软件一致；fallback 到开收差价
            pct = kline.get("pct_change") or (kline["close"] - kline["open"]) / kline["open"] * 100
            beat = 1 if pct > market_avg else 0
        else:
            pct = None
            beat = -1  # 无数据
        results.append({
            "stock_code": code,
            "stock_name": name,
            "rank": s.get("rank"),
            "total_score": s.get("total_score"),
            "d1_score": s.get("d1_score"),
            "d2_score": s.get("d2_score"),
            "d3_score": s.get("d3_score"),
            "d4_score": s.get("d4_score"),
            "d5_score": s.get("d5_score"),
            "d6_score": s.get("d6_score"),
            "open_price": kline["open"] if kline else None,
            "close_price": kline["close"] if kline else None,
            "pct_return": round(pct, 2) if pct is not None else None,
            "market_avg": market_avg,
            "beat_market": beat,
        })
    return results


def _build_human_message(perf_list: list, market_avg: float, run_date: str) -> str:
    """构建 LLM 输入消息"""
    total = len(perf_list)
    valid = [p for p in perf_list if p["pct_return"] is not None]
    beat_count = sum(1 for p in valid if p["beat_market"] == 1)
    avg_return = sum(p["pct_return"] for p in valid) / len(valid) if valid else 0.0
    win_rate = beat_count / len(valid) * 100 if valid else 0.0
    excess = avg_return - market_avg

    # 构建表格
    rows = []
    for p in sorted(perf_list, key=lambda x: x["rank"] or 99):
        pct_str = f"{p['pct_return']:+.2f}%" if p["pct_return"] is not None else "停牌/无数据"
        beat_str = "✅跑赢" if p["beat_market"] == 1 else ("❌跑输" if p["beat_market"] == 0 else "—")
        rows.append(
            f"| {p['rank']} | {p['stock_name']}({p['stock_code']}) "
            f"| {p['d1_score']} | {p['d2_score']} | {p['d3_score']} "
            f"| {p['d4_score']} | {p['d5_score']} | {p['d6_score']} "
            f"| {p['total_score']} | {pct_str} | {beat_str} |"
        )

    table = (
        "| 排名 | 股票 | D1 | D2 | D3 | D4 | D5 | D6 | 总分 | 当日涨跌 | 相对大盘 |\n"
        "|------|------|----|----|----|----|----|----|------|----------|----------|\n"
        + "\n".join(rows)
    )

    return (
        f"## 今日精筛验证数据 - {run_date}\n\n"
        f"**市场概况**：市场均值 {market_avg:+.2f}%，"
        f"推荐平均收益 {avg_return:+.2f}%，"
        f"超额收益 {excess:+.2f}%，"
        f"胜率 {win_rate:.0f}% ({beat_count}/{len(valid)}，共推荐{total}只，{total - len(valid)}只停牌/无数据)\n\n"
        f"**个股表现**（D1-D6各维度得分 + 当日实际表现）：\n\n"
        f"{table}\n\n"
        f"请根据以上数据，按照系统要求格式输出批评报告和改进版精筛Prompt。\n"
        f"（注意：在输出改进Prompt时，请直接参考原始精筛Prompt的完整内容，并在其基础上修改。）"
    )


def run_critic_agent(run_date: str = None) -> dict:
    """
    批评 Agent 主入口。
    1. 读取当日精筛结果
    2. 抓当日个股收盘价（开盘→收盘涨跌幅）
    3. LLM 批评分析 + 生成改进版 Prompt
    4. 自动激活新 Prompt，保留回滚 ID
    5. 保存结果到 DB
    """
    from tools.db import db
    from config.settings import build_llm as _build_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    today = run_date or datetime.now().strftime("%Y-%m-%d")
    logger.info(f"[批评Agent] 开始运行，日期={today}")

    # ── 1. 读取精筛结果 ────────────────────────────────────────────────────
    screener_rows = db.get_screener(today)
    if not screener_rows:
        msg = f"[批评Agent] {today} 无精筛数据，跳过"
        logger.warning(msg)
        return {"date": today, "error": msg, "screener_run_id": ""}

    screener_run_id = screener_rows[0].get("run_id", "") if screener_rows else ""
    logger.info(f"[批评Agent] 找到 {len(screener_rows)} 只精筛股票，run_id={screener_run_id}")

    # ── 2. 抓当日价格数据 ─────────────────────────────────────────────────
    market_avg = _get_market_avg()
    logger.info(f"[批评Agent] 市场均值={market_avg:.2f}%，开始抓个股数据...")
    perf_list = _build_performance_table(screener_rows, market_avg)

    valid = [p for p in perf_list if p["pct_return"] is not None]
    beat_count = sum(1 for p in valid if p["beat_market"] == 1)
    miss_count = sum(1 for p in valid if p["beat_market"] == 0)
    avg_pick_return = sum(p["pct_return"] for p in valid) / len(valid) if valid else 0.0
    logger.info(f"[批评Agent] 有数据 {len(valid)}/{len(perf_list)} 只，"
                f"跑赢 {beat_count}，跑输 {miss_count}，均值 {avg_pick_return:.2f}%")

    # ── 3. 读取当前激活的精筛 Prompt 可编辑部分（供 LLM 参考并改进） ──────────
    from agents.screener_agent import _SCREENER_EDITABLE as _se_default
    current_screener_editable = db.get_active_prompt("screener", "system_prompt") or _se_default

    # ── 4. 读取批评 Agent 的 Prompt（DB 优先，代码常量为后备，分两层组合） ──
    critic_editable = db.get_active_prompt("critic", "system_prompt")
    if not critic_editable:
        critic_editable = _CRITIC_EDITABLE
        try:
            db.save_prompt("critic", "system_prompt", _CRITIC_EDITABLE,
                           note="默认种子", active=True, source="human")
            logger.info("[批评Agent] 已将默认 Critic Prompt 种子化到 DB")
        except Exception as e:
            logger.warning(f"[批评Agent] 种子化 Critic Prompt 失败: {e}")
    # 固定输出格式部分始终附加（含哨兵分隔符）
    db.seed_output_format("critic", _CRITIC_OUTPUT_FORMAT)
    critic_fmt = db.get_output_format("critic") or _CRITIC_OUTPUT_FORMAT
    critic_prompt_content = critic_editable + "\n\n" + critic_fmt

    # ── 5. 构建 LLM 输入 ──────────────────────────────────────────────────
    human_msg = _build_human_message(perf_list, market_avg, today)
    # 只传精筛 Prompt 的可编辑部分（JSON 格式模板由系统自动附加，不暴露给 LLM）
    human_msg += (
        f"\n\n---\n## 当前精筛Prompt可编辑部分（请在此基础上修改，不要大幅重写）\n\n"
        f"```\n{current_screener_editable}\n```\n\n"
        f"⚠️ 注意：JSON输出格式模板由系统自动追加，你只需输出可编辑的分析准则部分。"
    )

    # ── 6. 调用 LLM ───────────────────────────────────────────────────────
    try:
        llm = _build_llm("critic")
        messages = [
            SystemMessage(content=critic_prompt_content),
            HumanMessage(content=human_msg),
        ]
        logger.info("[批评Agent] 调用 LLM 生成批评报告...")
        response = llm.invoke(messages)
        raw_output = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"[批评Agent] LLM 调用失败: {e}", exc_info=True)
        return {
            "date": today, "screener_run_id": screener_run_id,
            "error": f"LLM 调用失败: {e}",
            "stock_performance": perf_list,
            "avg_pick_return": avg_pick_return,
            "market_avg_return": market_avg,
            "beat_count": beat_count,
            "miss_count": miss_count,
        }

    # ── 7. 解析输出 ───────────────────────────────────────────────────────
    separator = "---SUGGESTED_PROMPT_BELOW---"
    if separator in raw_output:
        parts = raw_output.split(separator, 1)
        critique_markdown = parts[0].strip()
        suggested_prompt = parts[1].strip()
    else:
        critique_markdown = raw_output.strip()
        suggested_prompt = None
        logger.warning("[批评Agent] 未找到分隔符，无法提取改进 Prompt")

    # ── 8. 保存批评报告 ───────────────────────────────────────────────────
    # 提前记录当前激活的 screener prompt ID（供回滚用），直接传入报告记录
    previous_prompt_id = None
    for v in db.list_prompt_versions("screener"):
        if v.get("prompt_name") == "system_prompt" and v.get("is_active"):
            previous_prompt_id = v["id"]
            break

    critic_run_id, report_id = db.save_critic_report(
        run_date=today,
        screener_run_id=screener_run_id,
        critique_markdown=critique_markdown,
        avg_pick_return=avg_pick_return,
        market_avg_return=market_avg,
        beat_count=beat_count,
        miss_count=miss_count,
        suggested_prompt=suggested_prompt,
        previous_prompt_id=previous_prompt_id,
    )
    db.save_critic_performance(today, critic_run_id, perf_list)
    logger.info(f"[批评Agent] 已保存批评报告 run_id={critic_run_id}，前版本 id={previous_prompt_id}")

    # ── 9. 保存改进 Prompt（是否自动激活由 CRITIC_SCREENER_AUTO_ACTIVATE 控制）──
    auto_activate = os.getenv("CRITIC_SCREENER_AUTO_ACTIVATE", "false").strip().lower() == "true"
    suggested_prompt_id = None
    if suggested_prompt:
        try:
            suggested_prompt_id = db.save_prompt(
                "screener", "system_prompt", suggested_prompt,
                note=f"Critic自动生成 | {today}{'（已激活）' if auto_activate else '（待审核）'}",
                active=auto_activate,
                source="critic",
            )
            db.link_critic_prompt(report_id, suggested_prompt_id)
            logger.info(
                f"[批评Agent] 改进 Prompt 已保存 id={suggested_prompt_id}，"
                f"{'自动激活' if auto_activate else '待人工审核激活（CRITIC_SCREENER_AUTO_ACTIVATE=false）'}"
            )
        except Exception as e:
            logger.error(f"[批评Agent] 保存改进 Prompt 失败: {e}", exc_info=True)

    result = {
        "date": today,
        "screener_run_id": screener_run_id,
        "critic_run_id": critic_run_id,
        "critique_markdown": critique_markdown,
        "suggested_prompt": suggested_prompt,
        "suggested_prompt_id": suggested_prompt_id,
        "avg_pick_return": avg_pick_return,
        "market_avg_return": market_avg,
        "beat_count": beat_count,
        "miss_count": miss_count,
        "stock_performance": perf_list,
        "error": None,
    }
    logger.info(f"[批评Agent] 运行完成，胜率={beat_count}/{len(valid)}")
    return result
