"""个股分析 API：启动单股流程 + 历史查询。"""
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from api.deps import get_db

router = APIRouter(prefix="/api", tags=["stocks"])

_ROOT = Path(__file__).parent.parent.parent


@router.post("/stock")
def start_stock_analysis(
    payload: Dict[str, Any] = Body(...)
):
    """启动个股分析子进程。
    body: {"code_or_name": "300750", "with_peers": true}
    """
    code_or_name = payload.get("code_or_name")
    if not code_or_name:
        return {"status": "error", "error": "code_or_name required"}
    with_peers = bool(payload.get("with_peers", True))

    args = [sys.executable, "main.py", "--stock", str(code_or_name)]
    if not with_peers:
        args.append("--no-peers")
    proc = subprocess.Popen(
        args, cwd=str(_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"status": "started", "pid": proc.pid, "stock": code_or_name}


@router.get("/stocks/{code}/history")
def get_stock_history(code: str, limit: int = 50, db: Session = Depends(get_db)):
    """某股票跨 run 历史（来自 v_stock_analysis_history 视图）。"""
    rows = db.execute(
        text("SELECT * FROM v_stock_analysis_history WHERE code = :code "
             "ORDER BY rec_created_at DESC LIMIT :limit"),
        {"code": code, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]
