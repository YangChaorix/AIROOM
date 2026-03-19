"""
SQLite 统一存储管理器（v1.0）
单文件 SQLite，零安装，零内存常驻进程
文件路径：data/stock_agent.db
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS run_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date    TEXT NOT NULL,
    run_mode    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT DEFAULT 'running',
    error_msg   TEXT
);

CREATE TABLE IF NOT EXISTS triggers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date         TEXT NOT NULL,
    trigger_index    INTEGER,
    trigger_type     TEXT,
    summary          TEXT,
    industries       TEXT,
    companies        TEXT,
    strength         TEXT,
    freshness        TEXT,
    freshness_reason TEXT,
    caution          TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_triggers_date ON triggers(run_date);

CREATE TABLE IF NOT EXISTS screener_stocks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date       TEXT NOT NULL,
    rank           INTEGER,
    stock_name     TEXT,
    stock_code     TEXT,
    trigger_reason TEXT,
    d1_score       INTEGER, d1_reason TEXT,
    d2_score       INTEGER, d2_reason TEXT,
    d3_score       INTEGER, d3_reason TEXT,
    d4_score       INTEGER, d4_reason TEXT,
    d5_score       INTEGER, d5_reason TEXT,
    d6_score       INTEGER, d6_reason TEXT,
    total_score    INTEGER,
    recommendation TEXT,
    risk           TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_screener_date ON screener_stocks(run_date);
CREATE INDEX IF NOT EXISTS idx_screener_code ON screener_stocks(stock_code);

CREATE TABLE IF NOT EXISTS review_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date          TEXT NOT NULL UNIQUE,
    markdown_content  TEXT,
    market_up_count   INTEGER,
    market_down_count INTEGER,
    avg_pct_change    REAL,
    market_sentiment  TEXT,
    top_sectors       TEXT,
    is_friday         INTEGER,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    news_hash    TEXT NOT NULL,
    collect_date TEXT NOT NULL,
    title        TEXT,
    content      TEXT,
    source       TEXT,
    pub_time     TEXT,
    collected_at TEXT NOT NULL,
    priority     TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_news_hash_date ON news_items(news_hash, collect_date);
CREATE INDEX IF NOT EXISTS idx_news_date ON news_items(collect_date);
CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source, collect_date);

CREATE TABLE IF NOT EXISTS news_source_timestamps (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    collect_date   TEXT NOT NULL,
    source         TEXT NOT NULL,
    last_collected TEXT NOT NULL,
    UNIQUE(collect_date, source)
);

CREATE TABLE IF NOT EXISTS prompts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name  TEXT NOT NULL,
    prompt_name TEXT NOT NULL,
    content     TEXT NOT NULL,
    version     TEXT NOT NULL,
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT NOT NULL,
    note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_prompts_agent ON prompts(agent_name, is_active);

CREATE TABLE IF NOT EXISTS event_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_hash  TEXT NOT NULL UNIQUE,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    summary     TEXT,
    event_type  TEXT
);
"""


class StockAgentDB:
    DEFAULT_DB_PATH = "data/stock_agent.db"

    def __init__(self, db_path: str = None):
        if db_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(project_root, self.DEFAULT_DB_PATH)
        self.db_path = db_path
        # 首次使用时自动建表
        if not os.path.exists(self.db_path):
            try:
                self.init_db()
            except Exception as e:
                logger.warning(f"DB 自动初始化失败（不影响主流程）: {e}")

    def init_db(self) -> None:
        """建表（幂等，已存在不影响）"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(_DDL)
            conn.commit()
        finally:
            conn.close()
        logger.info(f"数据库初始化完成: {self.db_path}")

    @contextmanager
    def get_conn(self):
        """返回 sqlite3 connection（with 上下文管理器，自动 commit/rollback）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── run_logs ──────────────────────────────────────────────────────────────

    def start_run(self, run_mode: str) -> int:
        """记录运行开始，返回 run_id"""
        today = datetime.now().strftime("%Y-%m-%d")
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO run_logs (run_date, run_mode, started_at, status) VALUES (?, ?, ?, 'running')",
                (today, run_mode, started_at),
            )
            return cur.lastrowid

    def finish_run(self, run_id: int, status: str, error: str = None) -> None:
        """记录运行结束"""
        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE run_logs SET finished_at=?, status=?, error_msg=? WHERE id=?",
                (finished_at, status, error, run_id),
            )

    # ── triggers ──────────────────────────────────────────────────────────────

    def save_triggers(self, run_date: str, triggers: list) -> None:
        """保存当日触发信号（覆盖写）"""
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            conn.execute("DELETE FROM triggers WHERE run_date=?", (run_date,))
            for i, t in enumerate(triggers):
                conn.execute(
                    """INSERT INTO triggers
                       (run_date, trigger_index, trigger_type, summary, industries,
                        companies, strength, freshness, freshness_reason, caution, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_date, i + 1,
                        t.get("type", ""),
                        t.get("summary", ""),
                        json.dumps(t.get("industries", []), ensure_ascii=False),
                        json.dumps(t.get("companies", {}), ensure_ascii=False),
                        t.get("strength", ""),
                        t.get("freshness", ""),
                        t.get("freshness_reason", ""),
                        t.get("caution", ""),
                        created_at,
                    ),
                )
        logger.debug(f"save_triggers: {run_date} 写入 {len(triggers)} 条")

    def get_triggers(self, run_date: str) -> list:
        """读取某日触发信号"""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM triggers WHERE run_date=? ORDER BY trigger_index",
                (run_date,),
            ).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            r["industries"] = json.loads(r.get("industries") or "[]")
            r["companies"] = json.loads(r.get("companies") or "{}")
            result.append(r)
        return result

    # ── screener_stocks ───────────────────────────────────────────────────────

    def save_screener(self, run_date: str, top20: list) -> None:
        """保存当日精筛结果（覆盖写）"""
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            conn.execute("DELETE FROM screener_stocks WHERE run_date=?", (run_date,))
            for stock in top20:
                scores = stock.get("scores", {})

                def s(dim):
                    return scores.get(dim, {}).get("score")

                def r(dim):
                    return scores.get(dim, {}).get("reason", "")

                conn.execute(
                    """INSERT INTO screener_stocks
                       (run_date, rank, stock_name, stock_code, trigger_reason,
                        d1_score, d1_reason, d2_score, d2_reason,
                        d3_score, d3_reason, d4_score, d4_reason,
                        d5_score, d5_reason, d6_score, d6_reason,
                        total_score, recommendation, risk, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_date,
                        stock.get("rank"),
                        stock.get("name", ""),
                        stock.get("code", ""),
                        stock.get("trigger_reason", ""),
                        s("D1_龙头地位"), r("D1_龙头地位"),
                        s("D2_受益程度"), r("D2_受益程度"),
                        s("D3_股东结构"), r("D3_股东结构"),
                        s("D4_上涨趋势"), r("D4_上涨趋势"),
                        s("D5_技术突破"), r("D5_技术突破"),
                        s("D6_估值合理"), r("D6_估值合理"),
                        stock.get("total_score"),
                        stock.get("recommendation", ""),
                        stock.get("risk", ""),
                        created_at,
                    ),
                )
        logger.debug(f"save_screener: {run_date} 写入 {len(top20)} 条")

    def get_screener(self, run_date: str) -> list:
        """读取某日精筛结果"""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM screener_stocks WHERE run_date=? ORDER BY rank",
                (run_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_stock_history(self, stock_code: str, days: int = 30) -> list:
        """某只股票在近N天的历史出现记录"""
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT run_date, rank, total_score, recommendation
                   FROM screener_stocks
                   WHERE stock_code=?
                   ORDER BY run_date DESC
                   LIMIT ?""",
                (stock_code, days),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── review_reports ────────────────────────────────────────────────────────

    def save_review(self, run_date: str, review_result: dict) -> None:
        """保存复盘报告（按 run_date 唯一）"""
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ov = review_result.get("market_overview", {})
        top_sectors = review_result.get("top_sectors", [])
        with self.get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO review_reports
                   (run_date, markdown_content, market_up_count, market_down_count,
                    avg_pct_change, market_sentiment, top_sectors, is_friday, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_date,
                    review_result.get("review_markdown", ""),
                    ov.get("上涨家数"),
                    ov.get("下跌家数"),
                    ov.get("平均涨跌幅(%)"),
                    ov.get("市场情绪", ""),
                    json.dumps(top_sectors, ensure_ascii=False, default=str),
                    1 if review_result.get("is_friday") else 0,
                    created_at,
                ),
            )
        logger.debug(f"save_review: {run_date} 复盘报告已保存")

    def get_review(self, run_date: str) -> dict:
        """读取某日复盘报告"""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM review_reports WHERE run_date=?", (run_date,)
            ).fetchone()
        if row is None:
            return {}
        r = dict(row)
        r["top_sectors"] = json.loads(r.get("top_sectors") or "[]")
        return r

    # ── news_items ────────────────────────────────────────────────────────────

    def add_news_items(self, items: list, collect_date: str) -> int:
        """批量写入新闻，返回新增条数（按 news_hash+collect_date 去重）"""
        added = 0
        default_collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            for item in items:
                try:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO news_items
                           (news_hash, collect_date, title, content, source,
                            pub_time, collected_at, priority)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item.get("id", ""),
                            collect_date,
                            item.get("title", ""),
                            item.get("content", ""),
                            item.get("source", ""),
                            item.get("pub_time", ""),
                            item.get("collected_at", default_collected_at),
                            item.get("priority", "medium"),
                        ),
                    )
                    added += cur.rowcount
                except Exception as e:
                    logger.debug(f"add_news_items 跳过一条: {e}")
        return added

    def get_news(self, collect_date: str, source: str = None) -> list:
        """读取某日新闻列表"""
        with self.get_conn() as conn:
            if source:
                rows = conn.execute(
                    "SELECT * FROM news_items WHERE collect_date=? AND source=? ORDER BY collected_at",
                    (collect_date, source),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM news_items WHERE collect_date=? ORDER BY collected_at",
                    (collect_date,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_source_last_collected(self, collect_date: str) -> dict:
        """返回 {source: last_collected_time} 字典"""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT source, last_collected FROM news_source_timestamps WHERE collect_date=?",
                (collect_date,),
            ).fetchall()
        return {row["source"]: row["last_collected"] for row in rows}

    def mark_source_collected(self, collect_date: str, source: str) -> None:
        """更新某来源的采集时间戳"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO news_source_timestamps
                   (collect_date, source, last_collected) VALUES (?, ?, ?)""",
                (collect_date, source, now),
            )

    # ── prompts ───────────────────────────────────────────────────────────────

    def save_prompt(self, agent_name: str, prompt_name: str, content: str,
                    version: str, note: str = "") -> None:
        """保存新版本 Prompt（旧版本 is_active 设为 0）"""
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            conn.execute(
                "UPDATE prompts SET is_active=0 WHERE agent_name=? AND prompt_name=?",
                (agent_name, prompt_name),
            )
            conn.execute(
                """INSERT INTO prompts
                   (agent_name, prompt_name, content, version, is_active, created_at, note)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (agent_name, prompt_name, content, version, created_at, note),
            )

    def get_active_prompt(self, agent_name: str, prompt_name: str) -> Optional[str]:
        """读取当前激活的 Prompt 内容，不存在返回 None"""
        with self.get_conn() as conn:
            row = conn.execute(
                """SELECT content FROM prompts
                   WHERE agent_name=? AND prompt_name=? AND is_active=1
                   ORDER BY id DESC LIMIT 1""",
                (agent_name, prompt_name),
            ).fetchone()
        return row["content"] if row else None

    def list_prompt_versions(self, agent_name: str) -> list:
        """列出某 Agent 的所有 Prompt 版本"""
        with self.get_conn() as conn:
            rows = conn.execute(
                """SELECT id, prompt_name, version, is_active, created_at, note
                   FROM prompts WHERE agent_name=? ORDER BY id DESC""",
                (agent_name,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── event_history ─────────────────────────────────────────────────────────

    def get_event(self, event_hash: str) -> Optional[dict]:
        """读取某事件记录，不存在返回 None"""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM event_history WHERE event_hash=?", (event_hash,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_event(self, event_hash: str, summary: str, event_type: str,
                     first_seen: str, last_seen: str) -> None:
        """插入或更新事件记录（冲突时只更新 last_seen）"""
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO event_history (event_hash, first_seen, last_seen, summary, event_type)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(event_hash) DO UPDATE SET last_seen=excluded.last_seen""",
                (event_hash, first_seen, last_seen, summary, event_type),
            )

    def delete_old_events(self, before_date: str) -> int:
        """删除 last_seen < before_date 的事件，返回删除数量"""
        with self.get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM event_history WHERE last_seen < ?", (before_date,)
            )
            return cur.rowcount


db = StockAgentDB()  # 全局单例
