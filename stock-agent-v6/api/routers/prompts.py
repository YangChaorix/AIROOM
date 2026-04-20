"""Prompt 版本化 API：读当前 / 保存新版本 / 列历史 / 回滚 / diff。"""
import difflib
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from db.repos import prompt_versions_repo

router = APIRouter(prefix="/api", tags=["prompts"])

_VALID_AGENTS = {"supervisor", "research", "screener", "skeptic", "trigger"}


def _validate_agent(agent: str) -> None:
    if agent not in _VALID_AGENTS:
        raise HTTPException(400, f"agent 必须是 {_VALID_AGENTS}")


@router.get("/prompts/{agent}")
def get_prompt(agent: str, db: Session = Depends(get_db)):
    """返回当前活跃版本 + 历史版本列表。"""
    _validate_agent(agent)
    active = prompt_versions_repo.load_active_meta(db, agent)
    history = prompt_versions_repo.list_versions(db, agent, limit=50)
    return {
        "agent": agent,
        "active": active,
        "history": history,
    }


@router.post("/prompts/{agent}")
def save_new_prompt(
    agent: str,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
):
    """保存新版本。payload: {content, comment?, author?}"""
    _validate_agent(agent)
    content = payload.get("content")
    if not content:
        raise HTTPException(400, "content required")
    new_code = prompt_versions_repo.save_new(
        db,
        agent_name=agent,
        content=content,
        comment=payload.get("comment"),
        author=payload.get("author", "admin"),
        activate=True,
    )
    return {"status": "ok", "version_code": new_code}


@router.post("/prompts/{agent}/rollback/{version_code}")
def rollback_prompt(
    agent: str,
    version_code: str,
    payload: Optional[Dict[str, Any]] = Body(None),
    db: Session = Depends(get_db),
):
    _validate_agent(agent)
    try:
        new_code = prompt_versions_repo.rollback_to(
            db, agent, version_code, author=(payload or {}).get("author", "admin")
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"status": "ok", "new_version_code": new_code, "rolled_back_from": version_code}


@router.get("/prompts/{agent}/diff")
def diff_versions(
    agent: str,
    a: str = Query(...), b: str = Query(...),
    db: Session = Depends(get_db),
):
    """两版本 diff（unified format）。"""
    _validate_agent(agent)
    ca = prompt_versions_repo.get_version_content(db, agent, a)
    cb = prompt_versions_repo.get_version_content(db, agent, b)
    if ca is None or cb is None:
        raise HTTPException(404, "版本不存在")
    diff = list(difflib.unified_diff(
        ca.splitlines(keepends=True), cb.splitlines(keepends=True),
        fromfile=a, tofile=b,
    ))
    return {"agent": agent, "from": a, "to": b, "diff": "".join(diff)}
