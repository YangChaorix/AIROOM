"""新闻抓取任务定义。

每个任务函数接受一个渠道配置 dict，调 AkShare 拉数据 → upsert 到 news_items 表 → 失败入 system_logs。
所有函数共用同一模板，是"AkShare 接口名驱动"，支持任何返回 DataFrame 的 AkShare 新闻函数。
"""
import time
from typing import Any, Dict, List

import akshare as ak

from db.repos.news_items_repo import bulk_upsert
from db.repos.system_logs_repo import log, log_exception
from db.engine import get_session


def _df_to_items(df, source_label: str, adapter: str = "generic") -> List[Dict[str, Any]]:
    """把 AkShare 返回的 DataFrame 统一成 news_items_repo 期望的字典列表。

    adapter 决定从哪些列抽 title/content：
    - generic：标题/摘要/发布时间（默认，适用 news_cctv、stock_info_*_em）
    - economic_event：经济数据日历（日期 + 事件 + 公布 + 预期）
    - suspend_notice：停牌/复牌公告（股票简称 + 停牌事项说明）
    - research_report：券商研报（报告名称 + 机构 + 股票简称）
    """
    items = []
    if df is None or df.empty:
        return items
    cols = set(df.columns)

    def _s(v) -> str:
        if v is None:
            return ""
        s = str(v)
        return "" if s == "nan" else s

    def pick(row, *keys) -> str:
        for k in keys:
            if k in cols:
                v = _s(row.get(k))
                if v:
                    return v
        return ""

    for _, row in df.iterrows():
        if adapter == "economic_event":
            date = pick(row, "日期")
            time_ = pick(row, "时间")
            area = pick(row, "地区")
            event = pick(row, "事件")
            title = f"[{area}] {event}" if area and event else (event or "经济事件")
            content = f"公布: {pick(row,'公布')} / 预期: {pick(row,'预期')} / 前值: {pick(row,'前值')} / 重要性: {pick(row,'重要性')}"
            published_at = f"{date} {time_}".strip()
        elif adapter == "suspend_notice":
            code = pick(row, "股票代码")
            name = pick(row, "股票简称")
            reason = pick(row, "停牌事项说明")
            title = f"{name}({code}) {reason}"[:200]
            suspend = pick(row, "停牌时间")
            resume = pick(row, "复牌时间")
            content = f"停牌时间: {suspend} / 复牌时间: {resume or '待定'} / 市值: {pick(row,'市值')}"
            published_at = pick(row, "公告日期", "停牌时间")
        elif adapter == "research_report":
            name = pick(row, "股票简称")
            code = pick(row, "股票代码")
            rpt = pick(row, "报告名称")
            org = pick(row, "机构")
            rating = pick(row, "东财评级")
            title = f"[{org}/{rating}] {name}({code}) {rpt}"[:200]
            industry = pick(row, "行业")
            content = f"机构: {org} / 评级: {rating} / 行业: {industry}"
            published_at = pick(row, "日期")
        else:
            title = pick(row, "标题", "title")
            content = pick(row, "摘要", "content", "内容")
            published_at = pick(row, "发布时间", "date", "time", "pub_date")

        if not title:
            continue  # 关键字段缺失就跳过
        items.append({
            "title": title,
            "content": content,
            "source": source_label,
            "published_at": published_at,
        })
    return items


def fetch_channel(channel: Dict[str, Any]) -> Dict[str, Any]:
    """执行单个渠道的抓取任务。

    返回 {"inserted": N, "seen": M, "error": None/str}。
    失败时写 system_logs（error 级），不 raise。
    """
    name = channel["name"]
    func_name = channel["akshare_func"]
    source_label = channel.get("source_label", name)
    source_tag = f"scheduler.{name}"

    start = time.time()
    try:
        func = getattr(ak, func_name, None)
        if not callable(func):
            msg = f"AkShare 无此函数: {func_name}"
            log("error", source_tag, msg, context={"channel": channel})
            return {"inserted": 0, "seen": 0, "error": msg}

        df = func()
        adapter = channel.get("adapter", "generic")
        items = _df_to_items(df, source_label, adapter=adapter)
        if not items:
            log("warning", source_tag, f"渠道 {name} 返回空", context={"func": func_name})
            return {"inserted": 0, "seen": 0, "error": None}

        with get_session() as sess:
            result = bulk_upsert(sess, items)

        inserted = result["inserted"]
        dedup = result["dedup_hit"]
        elapsed_ms = int((time.time() - start) * 1000)
        log("info", source_tag,
            f"渠道 {name} 抓取完成：{len(items)} 条候选 → 新增 {inserted}，去重命中 {dedup}",
            context={"elapsed_ms": elapsed_ms, "func": func_name,
                     "inserted": inserted, "dedup_hit": dedup})
        return {"inserted": inserted, "dedup_hit": dedup, "seen": len(items), "error": None}

    except Exception as e:
        log_exception(source_tag, e, message=f"渠道 {name} 抓取失败")
        return {"inserted": 0, "seen": 0, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Agent 级任务（Phase 6）
# ─────────────────────────────────────────────────────────────

def run_trigger(**kwargs) -> Dict[str, Any]:
    """Scheduler 包装层：定时跑 Trigger Agent。

    **kwargs 直接透传给 agents.trigger.run_trigger。
    失败不 raise（写 system_logs）。
    """
    from agents.trigger import run_trigger as _run
    try:
        return _run(**kwargs)
    except Exception as e:
        log_exception("scheduler.trigger", e, message="Trigger 调度执行失败")
        return {"status": "error", "error": str(e)}


# task 名 → 函数的映射（scheduler/run.py 按 agent_schedule.json 的 task 字段查此表）
AGENT_TASKS = {
    "run_trigger": run_trigger,
}
