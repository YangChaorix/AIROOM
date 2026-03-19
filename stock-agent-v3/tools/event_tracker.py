"""
事件新鲜度追踪工具（v1.2：存储迁移至 SQLite）
跨日去重：将已见事件存储在 DB event_history 表，避免将持续性背景事件反复标注为新信息
"""

import hashlib
import logging
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

# 超过此天数视为低新鲜度
STALE_DAYS = 14

# 超过此天数自动清理
CLEANUP_DAYS = 30


def _make_event_hash(event_summary: str, event_type: str) -> str:
    """
    基于事件摘要前50字符 + 类型生成稳定哈希
    相同语义的事件应映射到相同哈希（尽力而为）
    """
    raw = (event_summary[:50] + "|" + event_type).strip().lower()
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def load_event_history() -> dict:
    """
    从 DB 加载事件历史

    Returns:
        {event_hash: {first_seen: "YYYY-MM-DD", summary: "...", type: "...", last_seen: "..."}}
    """
    from tools.db import db
    try:
        with db.get_conn() as conn:
            rows = conn.execute("SELECT * FROM event_history").fetchall()
        result = {}
        for row in rows:
            r = dict(row)
            result[r["event_hash"]] = {
                "first_seen": r["first_seen"],
                "last_seen": r["last_seen"],
                "summary": r.get("summary", ""),
                "type": r.get("event_type", ""),
            }
        return result
    except Exception as e:
        logger.warning(f"从 DB 加载事件历史失败: {e}，返回空历史")
        return {}


def save_event_history(history: dict) -> None:
    """
    将事件历史全量写入 DB（delete-all + insert-all，原子事务）

    Args:
        history: 事件历史字典
    """
    from tools.db import db
    try:
        with db.get_conn() as conn:
            conn.execute("DELETE FROM event_history")
            for event_hash, record in history.items():
                conn.execute(
                    """INSERT INTO event_history
                       (event_hash, first_seen, last_seen, summary, event_type)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        event_hash,
                        record.get("first_seen", ""),
                        record.get("last_seen", ""),
                        record.get("summary", ""),
                        record.get("type", ""),
                    ),
                )
    except Exception as e:
        logger.error(f"保存事件历史到 DB 失败: {e}")


def check_event_freshness(event_summary: str, event_type: str) -> dict:
    """
    检查事件新鲜度

    Args:
        event_summary: 事件摘要文本
        event_type: 事件类型（政策/涨价/转折事件）

    Returns:
        {
            is_fresh: bool,           # True 表示新事件或首次出现
            days_since_first: int,    # 距首次出现天数（0 = 今天首次）
            first_seen: str,          # 首次出现日期 "YYYY-MM-DD"
            freshness_label: str,     # "高" 或 "低"
            reason: str               # 判断理由
        }
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event_hash = _make_event_hash(event_summary, event_type)
    history = load_event_history()

    if event_hash not in history:
        # 首次出现：记录并返回高新鲜度
        history[event_hash] = {
            "first_seen": now_str,
            "summary": event_summary[:100],
            "type": event_type,
            "last_seen": now_str,
        }
        save_event_history(history)
        return {
            "is_fresh": True,
            "days_since_first": 0,
            "first_seen": now_str,
            "freshness_label": "高",
            "reason": "今日首次出现，为新增信息",
        }

    record = history[event_hash]
    first_seen_str = record.get("first_seen", now_str)
    try:
        first_seen_date = date.fromisoformat(first_seen_str[:10])
    except ValueError:
        first_seen_date = date.today()

    days_elapsed = (date.today() - first_seen_date).days

    # 更新 last_seen
    record["last_seen"] = now_str
    save_event_history(history)

    if days_elapsed > STALE_DAYS:
        return {
            "is_fresh": False,
            "days_since_first": days_elapsed,
            "first_seen": first_seen_str,
            "freshness_label": "低",
            "reason": f"该事件首次出现于 {first_seen_str}，已持续 {days_elapsed} 天（超过{STALE_DAYS}天），市场可能已 price in",
        }
    else:
        return {
            "is_fresh": True,
            "days_since_first": days_elapsed,
            "first_seen": first_seen_str,
            "freshness_label": "高",
            "reason": f"该事件首次出现于 {first_seen_str}，持续 {days_elapsed} 天，仍在新鲜窗口内",
        }


def mark_event_seen(event_summary: str, event_type: str) -> None:
    """
    标记事件为已见（如果历史中不存在则新增）

    Args:
        event_summary: 事件摘要文本
        event_type: 事件类型
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event_hash = _make_event_hash(event_summary, event_type)
    history = load_event_history()

    if event_hash not in history:
        history[event_hash] = {
            "first_seen": now_str,
            "summary": event_summary[:100],
            "type": event_type,
            "last_seen": now_str,
        }
    else:
        history[event_hash]["last_seen"] = now_str

    save_event_history(history)
    logger.debug(f"事件已标记: hash={event_hash}, type={event_type}, summary={event_summary[:50]}")


def cleanup_old_events(days: int = CLEANUP_DAYS) -> int:
    """
    清理超过指定天数未被重新见到的事件记录

    Args:
        days: 超过此天数（基于 last_seen）则清理，默认30天

    Returns:
        清理的条目数
    """
    history = load_event_history()
    cutoff = date.today() - timedelta(days=days)
    to_delete = []

    for event_hash, record in history.items():
        last_seen_str = record.get("last_seen", record.get("first_seen", "2000-01-01"))
        try:
            last_seen_date = date.fromisoformat(last_seen_str[:10])
        except ValueError:
            last_seen_date = date(2000, 1, 1)

        if last_seen_date < cutoff:
            to_delete.append(event_hash)

    for event_hash in to_delete:
        del history[event_hash]

    if to_delete:
        save_event_history(history)
        logger.info(f"事件历史清理完成：删除 {len(to_delete)} 条超过 {days} 天的记录")

    return len(to_delete)
