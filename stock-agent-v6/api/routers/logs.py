"""system_logs API：按 level / source 过滤。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from db.repos import system_logs_repo

router = APIRouter(prefix="/api", tags=["logs"])


@router.get("/logs")
def list_logs(
    level: Optional[str] = Query(None, description="info / warning / error"),
    source_prefix: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    return system_logs_repo.list_recent(
        level=level, source_prefix=source_prefix, limit=limit
    )
