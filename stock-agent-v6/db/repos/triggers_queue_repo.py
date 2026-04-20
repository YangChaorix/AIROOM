"""triggers 事件队列 Repository（Phase 6）。

提供 pending 队列的原子取单、标记处理、标记完成/失败功能。
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import Trigger


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
    """原子地取一个 pending trigger 并标记为 processing；取不到返回 None。

    按 priority DESC + created_at ASC（越老越优先）。
    """
    row = sess.scalar(
        select(Trigger)
        .where(Trigger.status == "pending")
        .order_by(Trigger.priority.desc(), Trigger.created_at.asc())
        .limit(1)
        .with_for_update()   # SQLite 忽略但兼容 PG
    )
    if row is None:
        return None
    row.status = "processing"
    sess.commit()
    return _trigger_to_dict(row)


def mark_completed(sess: Session, trigger_db_id: int, run_id: int) -> None:
    row = sess.scalar(select(Trigger).where(Trigger.id == trigger_db_id))
    if row is None:
        return
    row.status = "completed"
    row.consumed_by_run_id = run_id
    row.processed_at = datetime.utcnow()
    sess.commit()


def mark_failed(sess: Session, trigger_db_id: int, error: str) -> None:
    row = sess.scalar(select(Trigger).where(Trigger.id == trigger_db_id))
    if row is None:
        return
    row.status = "failed"
    row.processed_at = datetime.utcnow()
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
