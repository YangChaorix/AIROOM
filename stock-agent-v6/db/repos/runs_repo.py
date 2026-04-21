"""runs 表的 Repository。"""
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Run
from db.time_utils import now_local


def create_run(sess: Session, user_id: str, trigger_key: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> int:
    run = Run(
        user_id=user_id,
        trigger_key=trigger_key,
        status="running",
        started_at=now_local(),
        langsmith_project=os.getenv("LANGSMITH_PROJECT"),
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
    )
    sess.add(run)
    sess.flush()
    run_id = run.id
    sess.commit()
    return run_id


def mark_finished(sess: Session, run_id: int) -> None:
    run = sess.scalar(select(Run).where(Run.id == run_id))
    if run:
        run.status = "completed"
        run.finished_at = now_local()
        sess.commit()


def mark_failed(sess: Session, run_id: int, error: str) -> None:
    run = sess.scalar(select(Run).where(Run.id == run_id))
    if run:
        run.status = "failed"
        run.finished_at = now_local()
        run.error = error[:2000]
        sess.commit()


def list_recent(sess: Session, limit: int = 20) -> list:
    rows = sess.scalars(select(Run).order_by(Run.started_at.desc()).limit(limit)).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "trigger_key": r.trigger_key,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "error": r.error,
        }
        for r in rows
    ]
