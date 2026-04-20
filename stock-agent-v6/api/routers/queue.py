"""触发队列 API：状态统计 / pending 列表 / 消费。"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from db.models import Trigger

router = APIRouter(prefix="/api", tags=["queue"])

_ROOT = Path(__file__).parent.parent.parent


@router.get("/queue")
def get_queue_stats(db: Session = Depends(get_db)):
    """triggers 按 status 计数 + 列 pending 详情。"""
    counts = dict(
        db.execute(
            select(Trigger.status, func.count(Trigger.id)).group_by(Trigger.status)
        ).all()
    )

    pending = db.scalars(
        select(Trigger)
        .where(Trigger.status == "pending")
        .order_by(Trigger.priority.desc(), Trigger.created_at.asc())
        .limit(50)
    ).all()

    processing = db.scalars(
        select(Trigger).where(Trigger.status == "processing").limit(5)
    ).all()

    def _to_dict(t: Trigger) -> Dict[str, Any]:
        return {
            "id": t.id,
            "trigger_id": t.trigger_id,
            "headline": t.headline,
            "industry": t.industry,
            "type": t.type,
            "strength": t.strength,
            "priority": t.priority,
            "source": t.source,
            "mode": t.mode,
            "summary": t.summary,
            "status": t.status,
            "created_at": t.created_at,
            "processed_at": t.processed_at,
            "consumed_by_run_id": t.consumed_by_run_id,
            "source_news_ids": json.loads(t.source_news_ids) if t.source_news_ids else [],
            "metadata": json.loads(t.metadata_json) if t.metadata_json else {},
        }

    return {
        "counts": counts,
        "pending": [_to_dict(t) for t in pending],
        "processing": [_to_dict(t) for t in processing],
    }


@router.get("/triggers")
def list_triggers(status: str = Query(None), limit: int = Query(50, ge=1, le=500),
                  db: Session = Depends(get_db)):
    """按 status 筛选触发列表（用于"触发队列"tab）。"""
    stmt = select(Trigger)
    if status:
        stmt = stmt.where(Trigger.status == status)
    stmt = stmt.order_by(Trigger.priority.desc(), Trigger.created_at.desc()).limit(limit)
    rows = db.scalars(stmt).all()
    return [
        {
            "id": t.id, "trigger_id": t.trigger_id, "headline": t.headline,
            "industry": t.industry, "type": t.type, "strength": t.strength,
            "priority": t.priority, "status": t.status, "mode": t.mode,
            "summary": t.summary,
            "created_at": t.created_at, "processed_at": t.processed_at,
            "consumed_by_run_id": t.consumed_by_run_id,
        }
        for t in rows
    ]


@router.post("/queue/consume")
def consume_queue(n: int = Query(1, ge=1, le=10)):
    """启动后台子进程跑 `main.py --consume N`，立即返回（非阻塞）。

    真正的消费进度通过 SSE /api/stream 或轮询 /api/runs 观察。
    """
    py = sys.executable
    proc = subprocess.Popen(
        [py, "main.py", "--consume", str(n)],
        cwd=str(_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"status": "started", "pid": proc.pid, "n": n}
