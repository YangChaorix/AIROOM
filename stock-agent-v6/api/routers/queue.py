"""触发队列 API：状态统计 / pending 列表 / 消费。"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.deps import get_db
from db.models import Trigger


def _load_theme_stats(db: Session, keys: List[Tuple[str, str]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """按 (industry, type) 聚合主题级统计（只统计 mode='agent_generated'）。

    返回：{(industry, type): {first_seen, last_seen, total_hits, trigger_rows}}
    """
    if not keys:
        return {}
    # 用元组去重；subquery 里用 IN + (industry || '||' || type) 模拟 tuple in，兼容 SQLite
    unique = list({(i, t) for (i, t) in keys})
    cond = [(Trigger.industry == i) & (Trigger.type == t) for (i, t) in unique]

    rows = db.execute(
        select(
            Trigger.industry,
            Trigger.type,
            func.min(Trigger.created_at).label("first_seen"),
            func.max(func.coalesce(Trigger.last_seen_at, Trigger.created_at)).label("last_seen"),
            func.sum(Trigger.duplicate_count).label("total_hits"),
            func.count(Trigger.id).label("trigger_rows"),
        )
        .where(Trigger.mode == "agent_generated")
        .where(or_(*cond))
        .group_by(Trigger.industry, Trigger.type)
    ).all()

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in rows:
        out[(r.industry, r.type)] = {
            "theme_first_seen": r.first_seen,
            "theme_last_seen": r.last_seen,
            "theme_total_hits": int(r.total_hits or 0),
            "theme_trigger_rows": int(r.trigger_rows or 0),
        }
    return out

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

    all_rows = [*pending, *processing]
    theme_keys = [(t.industry, t.type) for t in all_rows if t.mode == "agent_generated"]
    theme_stats = _load_theme_stats(db, theme_keys)

    def _to_dict(t: Trigger) -> Dict[str, Any]:
        theme = theme_stats.get((t.industry, t.type)) if t.mode == "agent_generated" else None
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
            "duplicate_count": t.duplicate_count or 1,
            "last_seen_at": t.last_seen_at or t.created_at,
            "theme_stats": theme,
        }

    return {
        "counts": counts,
        "pending": [_to_dict(t) for t in pending],
        "processing": [_to_dict(t) for t in processing],
    }


@router.get("/triggers")
def list_triggers(status: str = Query(None), limit: int = Query(50, ge=1, le=500),
                  date: str = Query(None, description="YYYY-MM-DD，按 created_at 当天过滤"),
                  db: Session = Depends(get_db)):
    """按 status 筛选触发列表（用于"触发队列"tab）。"""
    from datetime import datetime, timedelta
    stmt = select(Trigger)
    if status:
        stmt = stmt.where(Trigger.status == status)
    if date:
        day_start = datetime.strptime(date, "%Y-%m-%d")
        day_end = day_start + timedelta(days=1)
        stmt = stmt.where(Trigger.created_at >= day_start, Trigger.created_at < day_end)
    stmt = stmt.order_by(Trigger.priority.desc(), Trigger.created_at.desc()).limit(limit)
    rows = db.scalars(stmt).all()

    theme_keys = [(t.industry, t.type) for t in rows if t.mode == "agent_generated"]
    theme_stats = _load_theme_stats(db, theme_keys)

    return [
        {
            "id": t.id, "trigger_id": t.trigger_id, "headline": t.headline,
            "industry": t.industry, "type": t.type, "strength": t.strength,
            "priority": t.priority, "status": t.status, "mode": t.mode,
            "summary": t.summary,
            "created_at": t.created_at, "processed_at": t.processed_at,
            "consumed_by_run_id": t.consumed_by_run_id,
            "duplicate_count": t.duplicate_count or 1,
            "last_seen_at": t.last_seen_at or t.created_at,
            "theme_stats": theme_stats.get((t.industry, t.type)) if t.mode == "agent_generated" else None,
        }
        for t in rows
    ]


_TRIGGER_LOCK = _ROOT / "data" / ".trigger_running.lock"
_TRIGGER_LOCK_MAX_AGE_SEC = 15 * 60  # 15 分钟超时兜底


def _pid_is_alive(pid: int) -> bool:
    """检查 pid 是否仍然是活进程（非僵尸）。

    FastAPI 用 Popen 起子进程但不 wait()，子进程退出后变僵尸进程（<defunct>）；
    `os.kill(pid, 0)` 对僵尸仍返回 True，会导致锁永远清不掉。
    先 waitpid(WNOHANG) 尝试回收僵尸；回收成功说明已退出 → 返回 False。
    """
    import os
    try:
        # 尝试回收僵尸子进程（只能收掉自己的子进程，对非子进程返回 ECHILD）
        try:
            reaped_pid, _ = os.waitpid(pid, os.WNOHANG)
            if reaped_pid == pid:
                return False  # 刚收到退出状态 → 已死
        except ChildProcessError:
            pass  # 不是本进程的子进程，继续 kill(0) 判断
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


@router.post("/triggers/run-now")
def run_trigger_now():
    """立即运行 Trigger Agent（扫描未消费 news → 生成 triggers）。

    通过 PID 文件防止并发：同一时刻只允许一个进程跑。
    失效锁清理策略：
      1. PID 已退出（含僵尸进程）→ 清锁
      2. 锁文件 mtime > 15 分钟 → 无条件清锁（兜底防挂机）
    """
    import os
    import time
    if _TRIGGER_LOCK.exists():
        age_sec = time.time() - _TRIGGER_LOCK.stat().st_mtime
        stale = False
        try:
            pid = int(_TRIGGER_LOCK.read_text().strip())
        except ValueError:
            stale = True
            pid = -1

        if not stale and _pid_is_alive(pid) and age_sec < _TRIGGER_LOCK_MAX_AGE_SEC:
            raise HTTPException(409, f"Trigger Agent 正在运行 (pid={pid})，请稍候")
        # 进入清理：僵尸/已退出/锁过期
        try:
            _TRIGGER_LOCK.unlink()
        except FileNotFoundError:
            pass

    _TRIGGER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "scheduler/run.py", "--once", "agents"],
        cwd=str(_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _TRIGGER_LOCK.write_text(str(proc.pid))
    return {"status": "started", "pid": proc.pid}


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
