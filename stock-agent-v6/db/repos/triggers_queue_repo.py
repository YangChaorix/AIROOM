"""triggers 事件队列 Repository（Phase 6）。

提供 pending 队列的原子取单、标记处理、标记完成/失败功能。
"""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import Trigger
from db.time_utils import now_local


def _trigger_to_dict(row: Trigger) -> Dict[str, Any]:
    """把 ORM 行转成 main.run() 期望的 trigger dict 格式。"""
    meta = json.loads(row.metadata_json) if row.metadata_json else {}
    source_ids = json.loads(row.source_news_ids) if row.source_news_ids else []
    return {
        "db_id": row.id,
        "trigger_id": row.trigger_id,
        "headline": row.headline,
        "industry": row.industry,
        "type": row.type,
        "strength": row.strength,
        "source": row.source,
        "published_at": str(row.published_at) if row.published_at else None,
        "summary": row.summary,
        "mode": row.mode,
        "source_news_ids": source_ids,
        "priority": row.priority,
        **meta,  # focus_codes / focus_primary / peer_names 若有
    }


def claim_next_pending(sess: Session) -> Optional[Dict[str, Any]]:
    """取下一条 pending trigger（按 priority DESC + created_at ASC）。

    **消费层同主题去重**：若候选的 (industry, type) 在当天 Shanghai 日历日内已有
    `completed` 的同模式 (mode='agent_generated') twin，则把候选标记为
    `skipped_duplicate`、挂靠到 twin 的 run，合并 source_news_ids 到 twin，
    循环找下一条。直到找到"无 twin"的 pending 或队列清空。

    **不参与主题去重的 mode**：
    - `individual_stock`（个股分析入口）—— 每次都要跑
    - `fixture` / `live`（调试用）—— 主题概念不适用
    只有 `agent_generated` 模式执行 twin 检查。
    """
    today_start = datetime.combine(now_local().date(), datetime.min.time())
    today_end = today_start + timedelta(days=1)

    while True:
        row = sess.scalar(
            select(Trigger)
            .where(Trigger.status == "pending")
            .order_by(Trigger.priority.desc(), Trigger.created_at.asc())
            .limit(1)
            .with_for_update()   # SQLite 忽略但兼容 PG
        )
        if row is None:
            return None

        # 只对 agent_generated 做主题去重；其它模式直通
        if row.mode != "agent_generated":
            row.status = "processing"
            sess.commit()
            return _trigger_to_dict(row)

        twin = sess.scalars(
            select(Trigger)
            .where(
                Trigger.id != row.id,
                Trigger.industry == row.industry,
                Trigger.type == row.type,
                Trigger.mode == "agent_generated",
                Trigger.status == "completed",
                Trigger.consumed_by_run_id.is_not(None),
                Trigger.created_at >= today_start,
                Trigger.created_at < today_end,
            )
            .order_by(Trigger.created_at.desc())
            .limit(1)
        ).first()

        if twin is None:
            row.status = "processing"
            sess.commit()
            return _trigger_to_dict(row)

        # 命中同主题 twin：合并 + 跳过
        _absorb_into_twin(sess, row, twin)
        # 继续循环找下一条


def _absorb_into_twin(sess: Session, src: Trigger, twin: Trigger) -> None:
    """把 src 的 source_news_ids 并入 twin，src 标为 skipped_duplicate 挂靠到 twin 的 run。

    news_items.consumed_by_trigger_id 不改动（保留"src 是原始入库者"的事实），
    但 twin.source_news_ids 会扩展为全集，供 v_recommendation_trace 完整反查。
    """
    try:
        src_ids = json.loads(src.source_news_ids) if src.source_news_ids else []
    except json.JSONDecodeError:
        src_ids = []
    try:
        twin_ids = json.loads(twin.source_news_ids) if twin.source_news_ids else []
    except json.JSONDecodeError:
        twin_ids = []
    merged = list(dict.fromkeys([*twin_ids, *src_ids]))

    now = now_local()
    twin.source_news_ids = json.dumps(merged, ensure_ascii=False)
    twin.duplicate_count = (twin.duplicate_count or 1) + 1
    twin.last_seen_at = now

    src.status = "skipped_duplicate"
    src.consumed_by_run_id = twin.consumed_by_run_id
    src.processed_at = now

    sess.commit()


def mark_completed(sess: Session, trigger_db_id: int, run_id: int) -> None:
    row = sess.scalar(select(Trigger).where(Trigger.id == trigger_db_id))
    if row is None:
        return
    row.status = "completed"
    row.consumed_by_run_id = run_id
    row.processed_at = now_local()
    sess.commit()


def mark_failed(sess: Session, trigger_db_id: int, error: str) -> None:
    row = sess.scalar(select(Trigger).where(Trigger.id == trigger_db_id))
    if row is None:
        return
    row.status = "failed"
    row.processed_at = now_local()
    # 把 error 写到 metadata_json 里（不新增列）
    try:
        meta = json.loads(row.metadata_json) if row.metadata_json else {}
    except Exception:
        meta = {}
    meta["error"] = error[:1000]
    row.metadata_json = json.dumps(meta, ensure_ascii=False)
    sess.commit()


def requeue(sess: Session, trigger_db_id: int) -> None:
    """把 processing / failed 的 trigger 重置回 pending（手动补救）。"""
    row = sess.scalar(select(Trigger).where(Trigger.id == trigger_db_id))
    if row is None:
        return
    row.status = "pending"
    row.consumed_by_run_id = None
    row.processed_at = None
    sess.commit()


def count_by_status() -> Dict[str, int]:
    from sqlalchemy import func
    with get_session() as sess:
        rows = sess.execute(
            select(Trigger.status, func.count(Trigger.id)).group_by(Trigger.status)
        ).all()
    return {r[0]: r[1] for r in rows}
