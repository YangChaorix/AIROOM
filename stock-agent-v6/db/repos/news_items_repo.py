"""news_items 表的 Repository（去重键 content_hash = SHA256(title+source)）。"""
import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import NewsItem


def _content_hash(title: str, source: str) -> str:
    return hashlib.sha256(f"{title}||{source}".encode("utf-8")).hexdigest()


def _parse_published_at(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            return datetime.strptime(s[:8], "%Y%m%d")
        except Exception:
            return None


def bulk_upsert(sess: Session, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """批量 upsert 新闻（按 content_hash 去重）。

    返回 {"ids": [...], "inserted": N, "dedup_hit": M}：
    - ids: 每条新闻（含去重命中的）对应的 news_items.id 列表
    - inserted: 本次真正新插入的行数
    - dedup_hit: 命中已有 content_hash 未插入的行数

    同标题同源跨天重复不会报错，但也不更新已有行（首次入库时间保留）。
    """
    ids: List[int] = []
    inserted = 0
    dedup_hit = 0
    for it in items:
        title = (it.get("title") or "").strip()
        source = (it.get("source") or "unknown").strip()
        if not title:
            continue
        hash_ = _content_hash(title, source)
        existing = sess.scalar(select(NewsItem).where(NewsItem.content_hash == hash_))
        if existing:
            ids.append(existing.id)
            dedup_hit += 1
            continue
        pub = _parse_published_at(it.get("published_at"))
        row = NewsItem(
            content_hash=hash_,
            title=title,
            content=(it.get("content") or "")[:500] or None,
            source=source,
            published_at=pub or datetime.utcnow(),
        )
        sess.add(row)
        sess.flush()
        ids.append(row.id)
        inserted += 1
    sess.commit()
    return {"ids": ids, "inserted": inserted, "dedup_hit": dedup_hit}
