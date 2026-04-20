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
    date: Optional[str] = Query(None, description="YYYY-MM-DD，按 created_at 当天过滤"),
    ids: Optional[str] = Query(None, description="按 ID 批量查（逗号分隔），如 '12,34,56'；指定后忽略其他过滤"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timedelta
    stmt = select(NewsItem)
    # 按 ID 批量查优先
    if ids:
        try:
            id_list = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            return []
        if not id_list:
            return []
        stmt = stmt.where(NewsItem.id.in_(id_list))
    else:
        if consumed is not None:
            if consumed:
                stmt = stmt.where(NewsItem.consumed_by_trigger_id.is_not(None))
            else:
                stmt = stmt.where(NewsItem.consumed_by_trigger_id.is_(None))
        if source:
            stmt = stmt.where(NewsItem.source == source)
        if date:
            day_start = datetime.strptime(date, "%Y-%m-%d")
            day_end = day_start + timedelta(days=1)
            stmt = stmt.where(NewsItem.created_at >= day_start, NewsItem.created_at < day_end)
    stmt = stmt.order_by(NewsItem.created_at.desc()).limit(limit)
    rows = db.scalars(stmt).all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "source": n.source,
            "published_at": n.published_at,
            "content": n.content or "",
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
