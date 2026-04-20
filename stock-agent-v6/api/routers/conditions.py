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
    """仅支持改权重 / 软删（active=false/true）。"""
    if "weight" in payload:
        ok = users_repo.update_condition_weight(db, user_id, condition_id, float(payload["weight"]))
        if not ok:
            raise HTTPException(404, f"condition {condition_id} not found")
        db.commit()

    if "active" in payload:
        # 软删：active=False；恢复：True（但 soft_delete 只支持置 False，需要扩展）
        from db.models import Condition
        from sqlalchemy import select
        existing = db.scalar(
            select(Condition).where(
                Condition.user_id == user_id,
                Condition.condition_id == condition_id,
            )
        )
        if not existing:
            raise HTTPException(404, f"condition {condition_id} not found")
        existing.active = bool(payload["active"])
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
