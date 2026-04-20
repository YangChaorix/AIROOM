"""Agent 状态 API：顶栏头像脉冲用。"""
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from db.models import AgentOutput

router = APIRouter(prefix="/api", tags=["agents"])

_AGENT_NAMES = ["supervisor", "research", "screener", "skeptic", "trigger"]


@router.get("/agents/status")
def agents_status(db: Session = Depends(get_db)):
    """每个 agent 最近 5 分钟内是否有活动 + 最近一次的信息。

    前端据此决定头像脉冲 / 灰度状态。
    """
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    result: List[Dict[str, Any]] = []
    for name in _AGENT_NAMES:
        latest = db.scalar(
            select(AgentOutput)
            .where(AgentOutput.agent_name == name)
            .order_by(AgentOutput.created_at.desc())
            .limit(1)
        )
        is_active = bool(latest and latest.created_at and latest.created_at >= cutoff)
        result.append({
            "name": name,
            "is_active": is_active,
            "last_activity_at": latest.created_at if latest else None,
            "last_run_id": latest.run_id if latest else None,
            "last_summary": (latest.summary[:80] if latest and latest.summary else None),
        })
    return result
