"""Trigger Agent（Phase 6）—— 从 news_items 队列读未消费新闻，LLM 筛选后生成 triggers。

调用路径：
  scheduler/tasks.py::run_trigger()（定时）
  main.py 也可直接调用（本地调试）

命名约定（与 supervisor/research/screener/skeptic 统一，无 _agent 后缀）：
  - 模块路径 agents.trigger
  - 入口函数 run_trigger()

设计：
- 读 news_items WHERE consumed_by_trigger_id IS NULL 且 created_at 在窗口内
- 调 chat LLM 按 config/prompts/trigger.md 筛选
- LLM 输出 "skip"  → 不生成 trigger
- LLM 输出 "generate" → 入 triggers(status='pending') + 更新 news_items.consumed_by_trigger_id
- 整个过程写 agent_outputs + system_logs
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from agents.llm_factory import build_llm
from db.engine import get_session
from db.models import AgentOutput, NewsItem, Trigger
from db.repos import agent_outputs_repo, users_repo
from db.repos.system_logs_repo import log, log_exception

_PROMPT_PATH = Path(__file__).parent.parent / "config" / "prompts" / "trigger.md"
_DEFAULT_USER_ID = "dad_001"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, re.DOTALL)
    return m.group(1).strip() if m else text


def _extract_json_obj(text: str) -> str:
    cleaned = _strip_code_fence(text)
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    start = cleaned.find("{")
    if start == -1:
        return cleaned
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1]
    return cleaned[start:]


def _fetch_pending_news(sess: Session, hours: int = 24, per_source_limit: int = 15,
                        global_limit: int = 80) -> List[NewsItem]:
    """读未消费且近 N 小时内的新闻。

    采用"**按渠道均衡采样**"：每个 source 取最新 per_source_limit 条，
    再合并按 created_at DESC 排，取全局前 global_limit。
    避免同批入库的大渠道（如 223 条券商研报）挤占候选池。
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    # 先列出所有活跃 source
    sources_stmt = (
        select(NewsItem.source)
        .where(and_(NewsItem.consumed_by_trigger_id.is_(None), NewsItem.created_at >= cutoff))
        .group_by(NewsItem.source)
    )
    sources = [r for r in sess.scalars(sources_stmt).all()]

    # 每个 source 取最新 per_source_limit 条
    collected: List[NewsItem] = []
    for src in sources:
        rows = sess.scalars(
            select(NewsItem)
            .where(and_(
                NewsItem.consumed_by_trigger_id.is_(None),
                NewsItem.created_at >= cutoff,
                NewsItem.source == src,
            ))
            .order_by(NewsItem.created_at.desc())
            .limit(per_source_limit)
        ).all()
        collected.extend(rows)

    # 合并按 created_at 全局排序，取 global_limit
    collected.sort(key=lambda r: r.created_at or datetime.min, reverse=True)
    return collected[:global_limit]


def _build_prompt(news_items: List[NewsItem], user_conditions: List[Dict[str, Any]]) -> str:
    now = datetime.utcnow()
    news_list = [
        {
            "id": n.id,
            "title": n.title[:200],
            "source": n.source,
            "published_at": str(n.published_at),
            "content_preview": (n.content or "")[:200],
        }
        for n in news_items
    ]
    # 只给 trigger 层和 screener 层条件（用户感兴趣的主题/行业）
    conditions_brief = [
        {"id": c["id"], "name": c["name"], "layer": c["layer"],
         "description": c["description"][:120], "keywords": c.get("keywords")}
        for c in user_conditions if c.get("layer") in ("trigger", "screener")
    ]
    tmpl = _PROMPT_PATH.read_text(encoding="utf-8")
    return tmpl.format(
        date=now.strftime("%Y%m%d"),
        user_conditions_json=json.dumps(conditions_brief, ensure_ascii=False, indent=2),
        news_count=len(news_list),
        news_list_json=json.dumps(news_list, ensure_ascii=False, indent=2),
    )


def _call_llm(prompt: str) -> str:
    llm = build_llm("research")  # 复用 chat 模型（trigger 筛选摘要任务）
    msg = llm.invoke(prompt)
    return msg.content if hasattr(msg, "content") else str(msg)


def run_trigger(hours: int = 24, user_id: str = _DEFAULT_USER_ID,
                      dry_run: bool = False) -> Dict[str, Any]:
    """主入口。dry_run=True 时不写 DB，仅打印 LLM 输出便于调试。"""
    source_tag = "agents.trigger"

    with get_session() as sess:
        news_items = _fetch_pending_news(sess, hours=hours)
        if not news_items:
            log("info", source_tag, "无新 news 可处理，skip")
            return {"status": "no_news", "created_trigger_id": None}

        try:
            profile = users_repo.load_profile(sess, user_id)
        except Exception as e:
            log_exception(source_tag, e, message="加载用户档案失败")
            return {"status": "error", "error": str(e)}

    prompt = _build_prompt(news_items, profile.get("conditions", []))

    try:
        raw_response = _call_llm(prompt)
    except Exception as e:
        log_exception(source_tag, e, message="Trigger Agent LLM 调用失败")
        return {"status": "llm_failed", "error": str(e)}

    try:
        decision = json.loads(_extract_json_obj(raw_response))
    except json.JSONDecodeError as e:
        log("error", source_tag, f"LLM 输出不是合法 JSON: {e}",
            context={"raw_preview": raw_response[:500]})
        return {"status": "parse_failed", "error": str(e)}

    action = decision.get("action", "skip")
    if dry_run:
        return {"status": "dry_run", "decision": decision,
                "news_candidates": len(news_items)}

    if action == "skip":
        log("info", source_tag,
            f"LLM 判断无值得分析的事件：{decision.get('reason','(无说明)')}",
            context={"news_candidates": len(news_items)})
        return {"status": "skipped", "reason": decision.get("reason")}

    if action != "generate":
        log("warning", source_tag, f"LLM 输出未知 action={action}",
            context={"decision": decision})
        return {"status": "unknown_action", "action": action}

    # 兼容两种格式：新格式 triggers:[...] / 老格式 trigger:{...}
    trigger_dicts: List[Dict[str, Any]] = []
    if isinstance(decision.get("triggers"), list):
        trigger_dicts = [t for t in decision["triggers"] if isinstance(t, dict)]
    elif isinstance(decision.get("trigger"), dict):
        trigger_dicts = [decision["trigger"]]

    if not trigger_dicts:
        log("warning", source_tag, "LLM 返回 generate 但未提供 trigger/triggers",
            context={"decision": decision})
        return {"status": "no_trigger_in_response", "decision": decision}

    candidate_ids = {n.id for n in news_items}
    results: List[Dict[str, Any]] = []
    consumed_ids_global: set[int] = set()

    for idx, trigger_dict in enumerate(trigger_dicts):
        source_news_ids = trigger_dict.get("source_news_ids") or []
        # 过滤：候选池里 && 未被本批前面的 trigger 消费过
        valid_ids = [
            nid for nid in source_news_ids
            if nid in candidate_ids and nid not in consumed_ids_global
        ]
        if not valid_ids:
            log("warning", source_tag,
                f"triggers[{idx}] 无有效 news_ids，跳过",
                context={"trigger": trigger_dict, "already_consumed_in_batch": list(consumed_ids_global)[:10]})
            results.append({"status": "no_valid_source", "index": idx})
            continue

        one = _persist_one_trigger(trigger_dict, valid_ids, len(news_items), source_tag)
        # 只要成功落库（generated/deduped），就把这些 ids 从本批剩余池里划走
        if one.get("status") in ("generated", "deduped"):
            consumed_ids_global.update(valid_ids)
        results.append({**one, "index": idx})

    generated_count = sum(1 for r in results if r.get("status") == "generated")
    deduped_count = sum(1 for r in results if r.get("status") == "deduped")
    log("info", source_tag,
        f"Trigger Agent 完成：新建 {generated_count} 条 / 去重命中 {deduped_count} 条 / "
        f"候选 news {len(news_items)} 条 / 已消费 {len(consumed_ids_global)} 条",
        context={"results_count": len(results)})

    return {
        "status": "generated" if generated_count > 0 else ("deduped" if deduped_count > 0 else "all_skipped"),
        "generated_count": generated_count,
        "deduped_count": deduped_count,
        "news_candidates": len(news_items),
        "news_consumed_total": len(consumed_ids_global),
        "triggers": results,
    }


def _persist_one_trigger(
    trigger_dict: Dict[str, Any],
    valid_ids: List[int],
    candidate_pool_size: int,
    source_tag: str,
) -> Dict[str, Any]:
    """把单条 trigger 落库（方案 C 去重 → 命中则累加，否则新建）。"""
    trigger_id_str = trigger_dict.get("trigger_id") or f"T-AGENT-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    headline = str(trigger_dict.get("headline", "自动生成触发"))[:200]
    priority = int(trigger_dict.get("priority", 5))
    strength = str(trigger_dict.get("strength", "medium"))
    industry = str(trigger_dict.get("industry", "通用"))
    trigger_type = str(trigger_dict.get("type", "industry_news"))

    with get_session() as sess:
        existing = _find_dedup_match(sess, industry, trigger_type)
        if existing is not None:
            result = _reinforce_existing(
                sess, existing, valid_ids, source_tag,
                headline, priority,
            )
            if result is not None:
                return result

        now = datetime.utcnow()
        row = Trigger(
            trigger_id=trigger_id_str,
            run_id=None,
            headline=headline,
            industry=industry,
            type=trigger_type,
            strength=strength,
            source=str(trigger_dict.get("source", "trigger")),
            published_at=_parse_dt(trigger_dict.get("published_at")),
            summary=str(trigger_dict.get("summary", ""))[:2000],
            mode="agent_generated",
            source_news_ids=json.dumps(valid_ids, ensure_ascii=False),
            metadata_json=json.dumps({
                "generated_by": "trigger",
                "candidate_pool_size": candidate_pool_size,
            }, ensure_ascii=False),
            status="pending",
            priority=priority,
            duplicate_count=1,
            last_seen_at=now,
        )
        sess.add(row)
        sess.flush()
        new_trigger_id = row.id

        affected = sess.query(NewsItem).filter(
            NewsItem.id.in_(valid_ids),
            NewsItem.consumed_by_trigger_id.is_(None),
        ).update(
            {NewsItem.consumed_by_trigger_id: new_trigger_id,
             NewsItem.consumed_at: now},
            synchronize_session=False,
        )
        if affected == 0:
            sess.rollback()
            log("warning", source_tag,
                "并发冲突：候选 news 已被其他触发消费",
                context={"valid_ids": valid_ids})
            return {"status": "race_conflict", "valid_ids": valid_ids}
        sess.commit()

    log("info", source_tag,
        f"生成 trigger id={new_trigger_id} headline={headline}",
        context={"trigger_id": new_trigger_id, "news_consumed": len(valid_ids),
                 "priority": priority, "strength": strength, "industry": industry})
    return {
        "status": "generated",
        "trigger_row_id": new_trigger_id,
        "trigger_id_str": trigger_id_str,
        "news_consumed": len(valid_ids),
        "headline": headline,
        "priority": priority,
    }


def _find_dedup_match(sess: Session, industry: str, trigger_type: str) -> Optional[Trigger]:
    """方案 C：两步查找同主题 trigger。

    Step 1：当天（UTC 日历日）任意状态的 (industry, type, mode='agent_generated')
    Step 2：跨天但 status='pending' 的 (industry, type, mode='agent_generated')

    找到则返回最新的一条；都未找到返回 None。
    """
    today_start = datetime.combine(datetime.utcnow().date(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    # Step 1：今日任何状态
    row = sess.scalars(
        select(Trigger)
        .where(
            Trigger.industry == industry,
            Trigger.type == trigger_type,
            Trigger.mode == "agent_generated",
            Trigger.created_at >= today_start,
            Trigger.created_at < today_end,
        )
        .order_by(Trigger.created_at.desc())
        .limit(1)
    ).first()
    if row is not None:
        return row

    # Step 2：历史 pending
    row = sess.scalars(
        select(Trigger)
        .where(
            Trigger.industry == industry,
            Trigger.type == trigger_type,
            Trigger.mode == "agent_generated",
            Trigger.status == "pending",
        )
        .order_by(Trigger.created_at.desc())
        .limit(1)
    ).first()
    return row


def _reinforce_existing(
    sess: Session,
    existing: Trigger,
    valid_ids: List[int],
    source_tag: str,
    new_headline: str,
    new_priority: int,
) -> Optional[Dict[str, Any]]:
    """命中已有 trigger：累加 duplicate_count + 并入 source_news_ids + 标记 news 已消费。

    不改 status（已 completed 的不退回 pending；pending 的保持 pending）。
    返回 dict 表示已处理完；返回 None 表示全部 news 已被并发消费，让上层 fallback。
    """
    now = datetime.utcnow()

    # 把 news 绑定到 existing trigger（乐观锁）
    affected = sess.query(NewsItem).filter(
        NewsItem.id.in_(valid_ids),
        NewsItem.consumed_by_trigger_id.is_(None),
    ).update(
        {NewsItem.consumed_by_trigger_id: existing.id,
         NewsItem.consumed_at: now},
        synchronize_session=False,
    )
    if affected == 0:
        # 所有 valid_ids 都已被并发消费 → 本次什么也不做
        sess.rollback()
        log("warning", source_tag,
            "并发冲突：候选 news 在去重命中后已被其他进程消费",
            context={"existing_id": existing.id, "valid_ids": valid_ids})
        return {"status": "race_conflict", "valid_ids": valid_ids}

    # 合并 source_news_ids
    try:
        old_ids = json.loads(existing.source_news_ids) if existing.source_news_ids else []
    except json.JSONDecodeError:
        old_ids = []
    merged_ids = list(dict.fromkeys([*old_ids, *valid_ids]))  # 去重保序

    existing.source_news_ids = json.dumps(merged_ids, ensure_ascii=False)
    existing.duplicate_count = (existing.duplicate_count or 1) + 1
    existing.last_seen_at = now
    # priority 取较高值（新批次如果更紧急可以抬升）
    if new_priority > (existing.priority or 0):
        existing.priority = new_priority

    sess.commit()

    log("info", source_tag,
        f"同主题 trigger 去重命中 id={existing.id} industry={existing.industry} "
        f"type={existing.type} dup_count={existing.duplicate_count}",
        context={
            "existing_id": existing.id,
            "existing_status": existing.status,
            "news_newly_consumed": len(valid_ids),
            "merged_source_news_ids_count": len(merged_ids),
            "new_headline": new_headline,
        })
    return {
        "status": "deduped",
        "trigger_row_id": existing.id,
        "trigger_id_str": existing.trigger_id,
        "existing_status": existing.status,
        "duplicate_count": existing.duplicate_count,
        "news_newly_consumed": len(valid_ids),
    }


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if "T" in s \
            else datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except Exception:
            return None
