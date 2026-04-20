"""用户条件 API：列表 / 编辑 / 软删 / 新增。"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import DEFAULT_USER_ID, get_db
from db.repos import users_repo

router = APIRouter(prefix="/api", tags=["conditions"])


@router.get("/conditions")
def list_conditions(user_id: str = DEFAULT_USER_ID, db: Session = Depends(get_db)):
    return users_repo.load_conditions(db, user_id, active_only=False)


@router.put("/conditions/{condition_id}")
def update_condition(
    condition_id: str,
    payload: Dict[str, Any] = Body(...),
    user_id: str = DEFAULT_USER_ID,
    db: Session = Depends(get_db),
):
    """支持改 weight / active / name / description / keywords。"""
    from db.models import Condition
    from sqlalchemy import select
    import json as _json

    existing = db.scalar(
        select(Condition).where(
            Condition.user_id == user_id,
            Condition.condition_id == condition_id,
        )
    )
    if not existing:
        raise HTTPException(404, f"condition {condition_id} not found")

    if "weight" in payload:
        existing.weight = float(payload["weight"]) if payload["weight"] is not None else None
    if "active" in payload:
        existing.active = bool(payload["active"])
    if "name" in payload:
        existing.name = str(payload["name"])
    if "description" in payload:
        existing.description = str(payload["description"])
    if "keywords" in payload:
        kw = payload["keywords"]
        existing.keywords_json = _json.dumps(kw, ensure_ascii=False) if kw else None

    db.commit()
    return {"status": "ok", "condition_id": condition_id}


@router.post("/conditions")
def upsert_condition(
    payload: Dict[str, Any] = Body(...),
    user_id: str = DEFAULT_USER_ID,
    db: Session = Depends(get_db),
):
    """新增或更新条件。payload: {id, name, layer, description, weight, keywords}"""
    users_repo.upsert_condition(db, user_id, payload)
    db.commit()
    return {"status": "ok", "condition_id": payload.get("id")}
