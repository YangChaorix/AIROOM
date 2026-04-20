"""news_items API（新闻流）。"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from db.models import NewsItem

router = APIRouter(prefix="/api", tags=["news"])


@router.get("/news")
def list_news(
    consumed: Optional[bool] = Query(None, description="true=已消费 / false=未消费 / 空=全部"),
    source: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(NewsItem)
    if consumed is not None:
        if consumed:
            stmt = stmt.where(NewsItem.consumed_by_trigger_id.is_not(None))
        else:
            stmt = stmt.where(NewsItem.consumed_by_trigger_id.is_(None))
    if source:
        stmt = stmt.where(NewsItem.source == source)
    stmt = stmt.order_by(NewsItem.created_at.desc()).limit(limit)
    rows = db.scalars(stmt).all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "source": n.source,
            "published_at": n.published_at,
            "content_preview": (n.content or "")[:200],
            "consumed_by_trigger_id": n.consumed_by_trigger_id,
            "consumed_at": n.consumed_at,
            "created_at": n.created_at,
        }
        for n in rows
    ]


@router.get("/news/stats")
def news_stats(db: Session = Depends(get_db)):
    """按 source 分组计数（供主页"今日概览"）。"""
    from sqlalchemy import func
    rows = db.execute(
        select(NewsItem.source, func.count(NewsItem.id)).group_by(NewsItem.source)
    ).all()
    return {
        "by_source": {r[0]: r[1] for r in rows},
        "total": sum(r[1] for r in rows),
    }
