"""FastAPI 依赖注入。"""
from typing import Generator

from sqlalchemy.orm import Session

from db.engine import get_session


def get_db() -> Generator[Session, None, None]:
    sess = get_session()
    try:
        yield sess
    finally:
        sess.close()


DEFAULT_USER_ID = "dad_001"
