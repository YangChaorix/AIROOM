"""system_logs 表的 Repository。

全局日志通道：调度器 / Agent / 工具层都可写入，DB 里统一查询。
"""
import json
import traceback
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import SystemLog

_LEVELS = {"info", "warning", "error"}


def log(level: str, source: str, message: str,
        context: Optional[Dict[str, Any]] = None,
        run_id: Optional[int] = None,
        session: Optional[Session] = None) -> None:
    """落一条日志到 DB。失败时 swallow 异常（不能让日志记录本身再 raise）。

    - level: 'info' / 'warning' / 'error'
    - source: 调用点标识，如 'scheduler.news_cctv' / 'agents.research'
    - message: 人可读的短消息
    - context: 任意扩展字典（异常信息 / 参数 / 返回预览），会 JSON 序列化
    - run_id: 可选，关联 runs.id
    - session: 若已有活跃 session 可传入（避免嵌套 commit）
    """
    if level not in _LEVELS:
        level = "info"
    try:
        row = SystemLog(
            level=level,
            source=source,
            message=message[:2000],
            context_json=json.dumps(context, ensure_ascii=False, default=str) if context else None,
            run_id=run_id,
        )
        if session is not None:
            session.add(row)
            return
        with get_session() as s:
            s.add(row)
            s.commit()
    except Exception as e:
        # 最终兜底：stderr，不再 raise
        import sys
        print(f"[system_logs] 日志写入失败: {e} — 原 message: {message[:80]}", file=sys.stderr)


def log_exception(source: str, exc: BaseException, message: Optional[str] = None,
                  context: Optional[Dict[str, Any]] = None,
                  run_id: Optional[int] = None) -> None:
    """异常专用：自动填入堆栈 + 异常类名。"""
    ctx = dict(context or {})
    ctx.update({
        "exc_type": type(exc).__name__,
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-3000:],
    })
    log("error", source, message or f"{type(exc).__name__}: {str(exc)[:200]}", context=ctx, run_id=run_id)


def list_recent(level: Optional[str] = None, source_prefix: Optional[str] = None,
                date: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    from datetime import datetime, timedelta
    stmt = select(SystemLog).order_by(SystemLog.created_at.desc()).limit(limit)
    if level:
        stmt = stmt.where(SystemLog.level == level)
    if source_prefix:
        stmt = stmt.where(SystemLog.source.like(f"{source_prefix}%"))
    if date:
        day_start = datetime.strptime(date, "%Y-%m-%d")
        day_end = day_start + timedelta(days=1)
        stmt = stmt.where(SystemLog.created_at >= day_start, SystemLog.created_at < day_end)
    with get_session() as sess:
        rows = sess.scalars(stmt).all()
        return [
            {
                "id": r.id,
                "level": r.level,
                "source": r.source,
                "message": r.message,
                "context": r.context_json,
                "run_id": r.run_id,
                "created_at": str(r.created_at),
            }
            for r in rows
        ]
