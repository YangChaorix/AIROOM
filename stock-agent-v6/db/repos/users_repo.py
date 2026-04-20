"""users + conditions 表的 Repository。

用法：
    with get_session() as sess:
        user = load_user(sess, "dad_001")
        conditions = load_conditions(sess, "dad_001")
"""
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Condition, User


def load_user(sess: Session, user_id: str) -> Optional[Dict[str, Any]]:
    row = sess.scalar(select(User).where(User.user_id == user_id))
    if row is None:
        return None
    return {
        "user_id": row.user_id,
        "name": row.name,
        "advanced_settings": {
            "recommendation_threshold": row.recommendation_threshold,
            "trading_style": row.trading_style,
        },
    }


def load_conditions(sess: Session, user_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
    """返回与 user_profile.json 里 `conditions` 数组等价的结构。"""
    stmt = select(Condition).where(Condition.user_id == user_id)
    if active_only:
        stmt = stmt.where(Condition.active.is_(True))
    conditions = sess.scalars(stmt).all()
    return [
        {
            "id": c.condition_id,
            "name": c.name,
            "layer": c.layer,
            "description": c.description,
            "weight": c.weight,
            "keywords": json.loads(c.keywords_json) if c.keywords_json else None,
            "active": bool(c.active),
        }
        for c in conditions
    ]


def load_profile(sess: Session, user_id: str) -> Dict[str, Any]:
    """聚合成与 config/user_profile.json 同形的 dict。"""
    user = load_user(sess, user_id)
    if user is None:
        raise ValueError(f"用户 {user_id} 不在 DB 中，请先跑 scripts/seed_from_json.py")
    conditions = load_conditions(sess, user_id)
    return {**user, "conditions": conditions}


def upsert_user(sess: Session, user_id: str, name: str, recommendation_threshold: float = 0.65,
                trading_style: Optional[str] = None) -> None:
    existing = sess.scalar(select(User).where(User.user_id == user_id))
    if existing:
        existing.name = name
        existing.recommendation_threshold = recommendation_threshold
        existing.trading_style = trading_style
    else:
        sess.add(User(
            user_id=user_id,
            name=name,
            recommendation_threshold=recommendation_threshold,
            trading_style=trading_style,
        ))


def upsert_condition(sess: Session, user_id: str, cond: Dict[str, Any]) -> None:
    existing = sess.scalar(
        select(Condition).where(
            Condition.user_id == user_id,
            Condition.condition_id == cond["id"],
        )
    )
    kwargs = {
        "name": cond["name"],
        "layer": cond["layer"],
        "description": cond["description"],
        "weight": cond.get("weight"),
        "keywords_json": json.dumps(cond["keywords"], ensure_ascii=False) if cond.get("keywords") else None,
    }
    if existing:
        for k, v in kwargs.items():
            setattr(existing, k, v)
    else:
        sess.add(Condition(user_id=user_id, condition_id=cond["id"], **kwargs))


def soft_delete_condition(sess: Session, user_id: str, condition_id: str) -> bool:
    existing = sess.scalar(
        select(Condition).where(
            Condition.user_id == user_id,
            Condition.condition_id == condition_id,
        )
    )
    if not existing:
        return False
    existing.active = False
    return True


def update_condition_weight(sess: Session, user_id: str, condition_id: str, weight: float) -> bool:
    existing = sess.scalar(
        select(Condition).where(
            Condition.user_id == user_id,
            Condition.condition_id == condition_id,
        )
    )
    if not existing:
        return False
    existing.weight = weight
    return True
