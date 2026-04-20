"""SQLAlchemy engine + session factory。

默认 DB 位于 data/stock_agent.db；可通过 STOCK_AGENT_DB_URL 环境变量覆盖
（测试用 sqlite:///:memory: 隔离）。
"""
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_ROOT = Path(__file__).parent.parent
_DEFAULT_DB_URL = f"sqlite:///{_ROOT / 'data' / 'stock_agent.db'}"

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_db_url() -> str:
    return os.getenv("STOCK_AGENT_DB_URL", _DEFAULT_DB_URL)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_db_url()
        # SQLite 需要 check_same_thread=False 以允许跨线程（测试 fixture 场景）
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, future=True, connect_args=connect_args)
        # SQLite 默认不启用外键约束，显式开启
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return _engine


def get_session() -> Session:
    """返回一个新的 Session；调用方负责 commit/close（或用 with 语句）。"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)
    return _SessionLocal()


def reset_engine() -> None:
    """测试用：在切换 DB URL 后强制重建 engine。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
