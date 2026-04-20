"""prompt_versions 表的 Repository —— Prompt 版本化 DB 存储。

核心场景：
- `load_active(agent_name)`：Agent 运行时读取当前激活 prompt
- `save_new(agent_name, content, comment, author)`：前端保存新版本，自动生成 version_code
- `rollback_to(agent_name, version_code)`：把某历史版本复制为新版本并激活
- `list_versions(agent_name, limit)`：前端浮层展示历史
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from db.models import PromptVersion


def _next_version_code(sess: Session, agent_name: str) -> str:
    """生成 YYYYMMDDNNNN 格式版本号。"""
    today_prefix = date.today().strftime("%Y%m%d")
    last = sess.scalar(
        select(PromptVersion)
        .where(
            PromptVersion.agent_name == agent_name,
            PromptVersion.version_code.like(f"{today_prefix}%"),
        )
        .order_by(desc(PromptVersion.version_code))
        .limit(1)
    )
    if last:
        next_seq = int(last.version_code[-4:]) + 1
    else:
        next_seq = 1
    return f"{today_prefix}{next_seq:04d}"


def load_active(sess: Session, agent_name: str) -> Optional[str]:
    """返回当前激活版本的 content；没有时返回 None（调用方 fallback 到 md 文件）。"""
    row = sess.scalar(
        select(PromptVersion).where(
            PromptVersion.agent_name == agent_name,
            PromptVersion.is_active.is_(True),
        )
    )
    return row.content if row else None


def load_active_meta(sess: Session, agent_name: str) -> Optional[Dict[str, Any]]:
    """同上但返回元信息（version_code + created_at + author + comment）。"""
    row = sess.scalar(
        select(PromptVersion).where(
            PromptVersion.agent_name == agent_name,
            PromptVersion.is_active.is_(True),
        )
    )
    if not row:
        return None
    return {
        "version_code": row.version_code,
        "content": row.content,
        "author": row.author,
        "comment": row.comment,
        "created_at": row.created_at,
    }


def save_new(sess: Session, agent_name: str, content: str,
             comment: Optional[str] = None, author: str = "admin",
             activate: bool = True) -> str:
    """保存新版本。默认激活（老版本 is_active 置 0）。返回新 version_code。"""
    if activate:
        sess.query(PromptVersion).filter(
            PromptVersion.agent_name == agent_name,
            PromptVersion.is_active.is_(True),
        ).update({PromptVersion.is_active: False}, synchronize_session=False)

    new_code = _next_version_code(sess, agent_name)
    row = PromptVersion(
        agent_name=agent_name,
        version_code=new_code,
        content=content,
        is_active=activate,
        author=author,
        comment=comment,
    )
    sess.add(row)
    sess.commit()
    return new_code


def rollback_to(sess: Session, agent_name: str, version_code: str,
                author: str = "admin") -> str:
    """把某历史版本复制为新版本并激活。保持版本线性。"""
    src = sess.scalar(
        select(PromptVersion).where(
            PromptVersion.agent_name == agent_name,
            PromptVersion.version_code == version_code,
        )
    )
    if not src:
        raise ValueError(f"版本 {version_code}（agent={agent_name}）不存在")
    return save_new(
        sess,
        agent_name=agent_name,
        content=src.content,
        comment=f"回滚至 {version_code}",
        author=author,
        activate=True,
    )


def list_versions(sess: Session, agent_name: str, limit: int = 50) -> List[Dict[str, Any]]:
    """按 created_at DESC 返回历史版本。"""
    rows = sess.scalars(
        select(PromptVersion)
        .where(PromptVersion.agent_name == agent_name)
        .order_by(desc(PromptVersion.created_at))
        .limit(limit)
    ).all()
    return [
        {
            "version_code": r.version_code,
            "is_active": r.is_active,
            "author": r.author,
            "comment": r.comment,
            "created_at": r.created_at,
            "content_preview": (r.content or "")[:120],
        }
        for r in rows
    ]


def get_version_content(sess: Session, agent_name: str, version_code: str) -> Optional[str]:
    row = sess.scalar(
        select(PromptVersion).where(
            PromptVersion.agent_name == agent_name,
            PromptVersion.version_code == version_code,
        )
    )
    return row.content if row else None
