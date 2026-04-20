"""triggers 表的 Repository。"""
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Trigger


def insert_trigger(sess: Session, run_id: int, trigger: Dict[str, Any],
                   mode: str = "live",
                   source_news_ids: Optional[List[int]] = None,
                   metadata: Optional[Dict[str, Any]] = None) -> int:
    """把 trigger dict（与 triggers_fixtures.json 同形）入库。

    source_news_ids 优先用参数；否则从 trigger dict 读取。
    metadata 优先用参数；否则从 trigger 里挑 focus_codes / focus_primary / peer_names 打包。

    trigger_id 唯一冲突处理（fixture 重复跑场景）：
    若已存在，自动给当前新行加 `-run{run_id}` 后缀保证唯一。
    生产环境 Trigger Agent 生成的 trigger_id 自带时间戳不会冲突。
    """
    if source_news_ids is None:
        source_news_ids = trigger.get("source_news_ids")

    if metadata is None:
        meta = {}
        for k in ("focus_codes", "focus_primary", "peer_names"):
            if k in trigger:
                meta[k] = trigger[k]
        metadata = meta if meta else None

    trigger_id = trigger["trigger_id"]
    # 冲突检查：已有同 trigger_id → 加 run 后缀
    existing = sess.scalar(select(Trigger).where(Trigger.trigger_id == trigger_id))
    if existing:
        trigger_id = f"{trigger_id}-run{run_id}"

    row = Trigger(
        trigger_id=trigger_id,
        run_id=run_id,
        headline=trigger["headline"],
        industry=trigger.get("industry", ""),
        type=trigger.get("type", "unknown"),
        strength=trigger.get("strength", "medium"),
        source=trigger.get("source", "unknown"),
        published_at=_parse_dt(trigger.get("published_at")),
        summary=trigger.get("summary", ""),
        mode=mode,
        source_news_ids=json.dumps(source_news_ids, ensure_ascii=False) if source_news_ids else None,
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
    )
    sess.add(row)
    sess.flush()
    tid = row.id
    sess.commit()
    return tid


def _parse_dt(s: Optional[str]):
    if not s:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if "T" in s else datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
