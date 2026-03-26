"""
SQLite 统一存储管理器（v1.0）
单文件 SQLite，零安装，零内存常驻进程
文件路径：data/db/stock_agent.db
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
    error_msg   TEXT,
    models      TEXT
);

CREATE TABLE IF NOT EXISTS triggers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date         TEXT NOT NULL,
    run_id           TEXT NOT NULL DEFAULT '',
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
    run_id         TEXT NOT NULL,
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
    trigger_index  INTEGER,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_screener_date ON screener_stocks(run_date);
CREATE INDEX IF NOT EXISTS idx_screener_run ON screener_stocks(run_date, run_id);
CREATE INDEX IF NOT EXISTS idx_screener_code ON screener_stocks(stock_code);

CREATE TABLE IF NOT EXISTS review_reports (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date          TEXT NOT NULL,
    run_id            TEXT NOT NULL DEFAULT '',
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
    seen_count  INTEGER NOT NULL DEFAULT 1,
    summary     TEXT,
    event_type  TEXT,
    source      TEXT
);

CREATE TABLE IF NOT EXISTS system_config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'number',
    label      TEXT,
    note       TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stock_analysis (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    codes          TEXT NOT NULL,
    names          TEXT,
    scores_summary TEXT,
    results        TEXT NOT NULL,
    model          TEXT,
    analyzed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stock_analysis_at ON stock_analysis(analyzed_at DESC);
"""

_DEFAULT_CONFIGS = [
    ("dashboard_picks_limit",        "10", "number", "控制台精选显示条数",      "控制台「今日精选」最多显示几条"),
    ("screener_news_sources",        "",   "text",   "初筛新闻渠道",            "空=所有渠道；多渠道逗号分隔，如：财联社,东方财富,国家发改委"),
    ("screener_news_lookback_hours", "0",  "number", "初筛新闻回溯小时数",      "0=仅当天（0点起）；24=过去24小时（含昨天）；48=过去48小时"),
    ("analyst_news_sources",         "",   "text",   "个股分析新闻渠道",        "空=所有渠道；多渠道逗号分隔，如：财联社,东方财富"),
    ("analyst_news_lookback_hours",  "72", "number", "个股分析新闻回溯小时数",  "默认72小时（近3天）；24=近1天；168=近7天"),
    ("schedule_trigger_hour",        "9",  "number", "触发分析执行小时",        "每天触发+精筛的小时（0-23，北京时间）"),
    ("schedule_trigger_minute",      "15", "number", "触发分析执行分钟",        "每天触发+精筛的分钟（0-59）"),
    ("schedule_trigger_days",        "1,2,3,4,5", "text", "触发分析执行日",   "周几执行，逗号分隔：1=周一…7=周日；空=每天"),
    ("schedule_review_hour",         "15", "number", "复盘执行小时",           "每天复盘的小时（0-23，北京时间）"),
    ("schedule_review_minute",       "35", "number", "复盘执行分钟",           "每天复盘的分钟（0-59）"),
    ("schedule_review_days",         "1,2,3,4,5", "text", "复盘执行日",        "周几执行，逗号分隔：1=周一…7=周日；空=每天"),
    ("log_retention_days",           "3",          "number", "日志保留天数",    "自动清理超出天数的日志文件，0=不清理"),
]


class StockAgentDB:
    DEFAULT_DB_PATH = "data/db/stock_agent.db"

    def __init__(self, db_path: str = None):
        if db_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(project_root, self.DEFAULT_DB_PATH)
        self.db_path = db_path
        # 每次启动都执行（幂等），确保迁移列存在
        try:
            self.init_db()
        except Exception as e:
            logger.warning(f"DB 初始化失败（不影响主流程）: {e}")

    def init_db(self) -> None:
        """建表（幂等，已存在不影响）"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(_DDL)
            conn.commit()
            # 迁移：run_logs 加 models 列
            cols = [r[1] for r in conn.execute("PRAGMA table_info(run_logs)").fetchall()]
            if "models" not in cols:
                conn.execute("ALTER TABLE run_logs ADD COLUMN models TEXT")
                conn.commit()
            # 迁移：screener_stocks 加 run_id 列
            cols = [r[1] for r in conn.execute("PRAGMA table_info(screener_stocks)").fetchall()]
            if "run_id" not in cols:
                conn.execute("ALTER TABLE screener_stocks ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
                conn.commit()
            # 迁移：event_history 加 seen_count 列
            cols = [r[1] for r in conn.execute("PRAGMA table_info(event_history)").fetchall()]
            if "seen_count" not in cols:
                conn.execute("ALTER TABLE event_history ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 1")
                conn.commit()
            # 迁移：event_history 加 source 列
            if "source" not in cols:
                conn.execute("ALTER TABLE event_history ADD COLUMN source TEXT")
                conn.commit()
            # 迁移：screener_stocks 加 trigger_index 列
            cols = [r[1] for r in conn.execute("PRAGMA table_info(screener_stocks)").fetchall()]
            if "trigger_index" not in cols:
                conn.execute("ALTER TABLE screener_stocks ADD COLUMN trigger_index INTEGER")
                conn.commit()
            # 迁移：review_reports 去掉 run_date UNIQUE 约束，加 run_id 列
            cols = [r[1] for r in conn.execute("PRAGMA table_info(review_reports)").fetchall()]
            if "run_id" not in cols:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS review_reports_new (
                        id                INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_date          TEXT NOT NULL,
                        run_id            TEXT NOT NULL DEFAULT '',
                        markdown_content  TEXT,
                        market_up_count   INTEGER,
                        market_down_count INTEGER,
                        avg_pct_change    REAL,
                        market_sentiment  TEXT,
                        top_sectors       TEXT,
                        is_friday         INTEGER,
                        created_at        TEXT NOT NULL
                    );
                    INSERT INTO review_reports_new
                        SELECT id, run_date, COALESCE(created_at,''), markdown_content,
                               market_up_count, market_down_count, avg_pct_change,
                               market_sentiment, top_sectors, is_friday, created_at
                        FROM review_reports;
                    DROP TABLE review_reports;
                    ALTER TABLE review_reports_new RENAME TO review_reports;
                    CREATE INDEX IF NOT EXISTS idx_review_run ON review_reports(run_date, run_id);
                """)
            # 迁移：triggers 加 run_id 列
            cols = [r[1] for r in conn.execute("PRAGMA table_info(triggers)").fetchall()]
            if "run_id" not in cols:
                conn.execute("ALTER TABLE triggers ADD COLUMN run_id TEXT NOT NULL DEFAULT ''")
                # 回填：用 created_at 作为旧数据的 run_id（按 run_date 分组，同一天同一批）
                conn.execute("""
                    UPDATE triggers SET run_id = (
                        SELECT MIN(created_at) FROM triggers t2 WHERE t2.run_date = triggers.run_date
                    ) WHERE run_id = ''
                """)
                conn.commit()
            # 迁移完成后确保 run_id 相关索引存在（DDL 中已移除，这里统一创建）
            conn.execute("CREATE INDEX IF NOT EXISTS idx_triggers_run ON triggers(run_date, run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_run ON review_reports(run_date, run_id)")
            conn.commit()
            # 迁移：stock_analysis 加 names / scores_summary 列
            cols = [r[1] for r in conn.execute("PRAGMA table_info(stock_analysis)").fetchall()]
            if "names" not in cols:
                conn.execute("ALTER TABLE stock_analysis ADD COLUMN names TEXT")
                conn.commit()
            if "scores_summary" not in cols:
                conn.execute("ALTER TABLE stock_analysis ADD COLUMN scores_summary TEXT")
                conn.commit()
            # 迁移：回填 names / scores_summary 为 NULL 的旧记录
            old_rows = conn.execute(
                "SELECT id, results FROM stock_analysis WHERE names IS NULL OR scores_summary IS NULL"
            ).fetchall()
            for old_row in old_rows:
                try:
                    res = json.loads(old_row[1])
                    stock_results = res.get("results", [])
                    names = []
                    scores_summary = []
                    for r in stock_results:
                        basic = (r.get("raw_data") or {}).get("basic") or {}
                        name = (basic.get("股票名称") or basic.get("股票简称")
                                or r.get("name") or r.get("code", ""))
                        ts = r.get("total_score")
                        if ts is None:
                            sc = r.get("scores") or {}
                            if sc:
                                ts = sum(v.get("score", 0) for v in sc.values() if isinstance(v, dict))
                        names.append(name)
                        scores_summary.append({
                            "code": r.get("code", ""),
                            "name": name,
                            "total_score": ts,
                        })
                    conn.execute(
                        "UPDATE stock_analysis SET names=?, scores_summary=? WHERE id=?",
                        (json.dumps(names, ensure_ascii=False),
                         json.dumps(scores_summary, ensure_ascii=False),
                         old_row[0]),
                    )
                except Exception:
                    pass
            conn.commit()
            # 初始化默认系统配置（已存在的 key 跳过）
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for key, value, typ, label, note in _DEFAULT_CONFIGS:
                conn.execute(
                    """INSERT OR IGNORE INTO system_config (key, value, type, label, note, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (key, value, typ, label, note, now),
                )
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

    def start_run(self, run_mode: str, models: dict = None) -> int:
        """记录运行开始，返回 run_id。models 格式：{agent: 'provider/model-id'}"""
        today = datetime.now().strftime("%Y-%m-%d")
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        models_json = json.dumps(models, ensure_ascii=False) if models else None
        with self.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO run_logs (run_date, run_mode, started_at, status, models) VALUES (?, ?, ?, 'running', ?)",
                (today, run_mode, started_at, models_json),
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
        """保存当日触发信号（追加写，每次生成新 run_id）"""
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        run_id = created_at  # 同一批次共用同一个时间戳
        with self.get_conn() as conn:
            for i, t in enumerate(triggers):
                conn.execute(
                    """INSERT INTO triggers
                       (run_date, run_id, trigger_index, trigger_type, summary, industries,
                        companies, strength, freshness, freshness_reason, caution, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_date, run_id, i + 1,
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
        logger.debug(f"save_triggers: {run_date} run_id={run_id} 写入 {len(triggers)} 条")

    def get_trigger_run_ids(self, run_date: str) -> list:
        """返回某日所有触发批次 run_id，按时间倒序"""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_id FROM triggers WHERE run_date=? ORDER BY run_id DESC",
                (run_date,),
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def get_triggers(self, run_date: str, run_id: str = None) -> list:
        """读取某日触发信号；run_id 为空则返回最新批次"""
        with self.get_conn() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM triggers WHERE run_date=? AND run_id=? ORDER BY trigger_index",
                    (run_date, run_id),
                ).fetchall()
            else:
                latest = conn.execute(
                    "SELECT run_id FROM triggers WHERE run_date=? ORDER BY run_id DESC LIMIT 1",
                    (run_date,),
                ).fetchone()
                if not latest:
                    return []
                rows = conn.execute(
                    "SELECT * FROM triggers WHERE run_date=? AND run_id=? ORDER BY trigger_index",
                    (run_date, latest[0]),
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
        """保存精筛结果（追加，每次分析生成新的 run_id）"""
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        run_id = created_at  # 同一批次共用同一个时间戳
        with self.get_conn() as conn:
            for stock in top20:
                scores = stock.get("scores", {})

                def s(dim):
                    return scores.get(dim, {}).get("score")

                def r(dim):
                    return scores.get(dim, {}).get("reason", "")

                conn.execute(
                    """INSERT INTO screener_stocks
                       (run_date, run_id, rank, stock_name, stock_code, trigger_reason,
                        d1_score, d1_reason, d2_score, d2_reason,
                        d3_score, d3_reason, d4_score, d4_reason,
                        d5_score, d5_reason, d6_score, d6_reason,
                        total_score, recommendation, risk, trigger_index, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_date,
                        run_id,
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
                        stock.get("trigger_index"),
                        created_at,
                    ),
                )
        logger.debug(f"save_screener: {run_date} run_id={run_id} 写入 {len(top20)} 条")

    def get_screener_run_ids(self, run_date: str) -> list:
        """返回某日所有精筛批次 run_id，按时间倒序"""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_id FROM screener_stocks WHERE run_date=? ORDER BY run_id DESC",
                (run_date,),
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def get_screener(self, run_date: str, run_id: str = None) -> list:
        """读取某日精筛结果；run_id 为空则返回最新批次"""
        with self.get_conn() as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM screener_stocks WHERE run_date=? AND run_id=? ORDER BY rank",
                    (run_date, run_id),
                ).fetchall()
            else:
                # 取最新批次
                latest = conn.execute(
                    "SELECT run_id FROM screener_stocks WHERE run_date=? ORDER BY run_id DESC LIMIT 1",
                    (run_date,),
                ).fetchone()
                if not latest:
                    return []
                rows = conn.execute(
                    "SELECT * FROM screener_stocks WHERE run_date=? AND run_id=? ORDER BY rank",
                    (run_date, latest[0]),
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
        """保存复盘报告（追加写，每次生成新 run_id）"""
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        run_id = created_at
        ov = review_result.get("market_overview", {})
        top_sectors = review_result.get("top_sectors", [])
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO review_reports
                   (run_date, run_id, markdown_content, market_up_count, market_down_count,
                    avg_pct_change, market_sentiment, top_sectors, is_friday, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_date, run_id,
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
        logger.debug(f"save_review: {run_date} run_id={run_id} 复盘报告已保存")

    def get_review_run_ids(self, run_date: str) -> list:
        """返回某日所有复盘批次 run_id，按时间倒序"""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_id FROM review_reports WHERE run_date=? ORDER BY run_id DESC",
                (run_date,),
            ).fetchall()
        return [r[0] for r in rows if r[0]]

    def get_review(self, run_date: str, run_id: str = None) -> dict:
        """读取某日复盘报告；run_id 为空则返回最新批次"""
        with self.get_conn() as conn:
            if run_id:
                row = conn.execute(
                    "SELECT * FROM review_reports WHERE run_date=? AND run_id=?",
                    (run_date, run_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM review_reports WHERE run_date=? ORDER BY run_id DESC LIMIT 1",
                    (run_date,),
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

    def get_news_filtered(self, sources: list = None, since_dt: str = None) -> list:
        """
        按来源和时间过滤新闻（可跨日）。
        sources: None 或 [] = 所有来源；否则只返回指定来源
        since_dt: None = 今天0点起；YYYY-MM-DD HH:MM:SS 格式的起始时间
        """
        if since_dt is None:
            since_dt = datetime.now().strftime("%Y-%m-%d") + " 00:00:00"
        params: list = [since_dt]
        where = "WHERE collected_at >= ?"
        if sources:
            placeholders = ",".join("?" * len(sources))
            where += f" AND source IN ({placeholders})"
            params.extend(sources)
        with self.get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM news_items {where} ORDER BY collected_at",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def search_news(self, keywords: list, days: int = 3, limit: int = 15,
                    sources: list = None, since_dt: str = None) -> list:
        """
        搜索标题或内容包含任一关键词的新闻，按发布时间倒序。
        sources: None/[] = 所有渠道；否则只搜指定渠道
        since_dt: YYYY-MM-DD HH:MM:SS 起始时间；None 则用 days 参数计算
        """
        if not keywords:
            return []
        keyword_cond = " OR ".join(["(title LIKE ? OR content LIKE ?)"] * len(keywords))
        params = []
        for kw in keywords:
            params.extend([f"%{kw}%", f"%{kw}%"])

        if since_dt:
            time_cond = "collected_at >= ?"
            params.append(since_dt)
        else:
            time_cond = f"collect_date >= date('now', '-{int(days)} days')"

        source_cond = ""
        if sources:
            placeholders = ",".join("?" * len(sources))
            source_cond = f"AND source IN ({placeholders})"
            params.append(*sources) if len(sources) == 1 else params.extend(sources)

        with self.get_conn() as conn:
            rows = conn.execute(
                f"""SELECT title, source, pub_time, content FROM news_items
                    WHERE {time_cond}
                    AND ({keyword_cond})
                    {source_cond}
                    ORDER BY COALESCE(pub_time, collected_at) DESC
                    LIMIT ?""",
                params + [limit],
            ).fetchall()
        return [dict(r) for r in rows]

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
                    version: str = None, note: str = "") -> int:
        """保存新版本 Prompt（旧版本 is_active 设为 0），返回新行 id"""
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            # 自动生成版本号
            if version is None:
                rows = conn.execute(
                    "SELECT version FROM prompts WHERE agent_name=? AND prompt_name=?",
                    (agent_name, prompt_name),
                ).fetchall()
                max_n = 0
                for row in rows:
                    v = row["version"] or ""
                    if v.startswith("v"):
                        try:
                            max_n = max(max_n, int(v[1:].split(".")[0]))
                        except ValueError:
                            pass
                version = f"v{max_n + 1}"

            # 旧版本全部归档
            conn.execute(
                "UPDATE prompts SET is_active=0 WHERE agent_name=? AND prompt_name=?",
                (agent_name, prompt_name),
            )
            # 插入新版本
            cur = conn.execute(
                """INSERT INTO prompts
                   (agent_name, prompt_name, content, version, is_active, created_at, note)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (agent_name, prompt_name, content, version, created_at, note),
            )
            new_id = cur.lastrowid

            # 100 条上限：删除最旧的超出部分
            conn.execute(
                """DELETE FROM prompts WHERE agent_name=? AND prompt_name=?
                   AND id NOT IN (
                     SELECT id FROM prompts WHERE agent_name=? AND prompt_name=?
                     ORDER BY id DESC LIMIT 100
                   )""",
                (agent_name, prompt_name, agent_name, prompt_name),
            )
            return new_id

    def activate_prompt(self, prompt_id: int) -> bool:
        """将指定 id 的 Prompt 设为激活，同 agent/name 其余版本归档"""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT agent_name, prompt_name FROM prompts WHERE id=?", (prompt_id,)
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE prompts SET is_active=0 WHERE agent_name=? AND prompt_name=?",
                (row["agent_name"], row["prompt_name"]),
            )
            conn.execute("UPDATE prompts SET is_active=1 WHERE id=?", (prompt_id,))
            return True

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

    def news_seen_before(self, news_hash: str, today: str) -> Optional[str]:
        """若该 news_hash 在 today 之前的日期已存在，返回最早日期；否则返回 None"""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT MIN(collect_date) as first_date FROM news_items WHERE news_hash=? AND collect_date<?",
                (news_hash, today),
            ).fetchone()
        first = row["first_date"] if row else None
        return first if first else None

    # ── event_history ─────────────────────────────────────────────────────────

    def get_event(self, event_hash: str) -> Optional[dict]:
        """读取某事件记录，不存在返回 None"""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM event_history WHERE event_hash=?", (event_hash,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_event(self, event_hash: str, summary: str, event_type: str,
                     first_seen: str, last_seen: str, source: str = None) -> None:
        """插入或更新事件记录（冲突时更新 last_seen 并累计 seen_count）"""
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO event_history (event_hash, first_seen, last_seen, seen_count, summary, event_type, source)
                   VALUES (?, ?, ?, 1, ?, ?, ?)
                   ON CONFLICT(event_hash) DO UPDATE SET
                       last_seen=excluded.last_seen,
                       seen_count=seen_count+1,
                       source=COALESCE(excluded.source, source)""",
                (event_hash, first_seen, last_seen, summary, event_type, source),
            )

    def delete_old_events(self, before_date: str) -> int:
        """删除 last_seen < before_date 的事件，返回删除数量"""
        with self.get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM event_history WHERE last_seen < ?", (before_date,)
            )
            return cur.rowcount

    # ── system_config ──────────────────────────────────────────────────────────

    def get_all_configs(self) -> list:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT * FROM system_config ORDER BY key").fetchall()
        return [dict(r) for r in rows]

    def get_config(self, key: str, default=None):
        with self.get_conn() as conn:
            row = conn.execute("SELECT value, type FROM system_config WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        value, typ = row["value"], row["type"]
        if typ == "number":
            try:
                return int(value)
            except ValueError:
                return float(value)
        return value

    def set_config(self, key: str, value: str) -> bool:
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_conn() as conn:
            cur = conn.execute(
                "UPDATE system_config SET value=?, updated_at=? WHERE key=?",
                (value, updated_at, key),
            )
        return cur.rowcount > 0

    # ── stock_analysis ────────────────────────────────────────────────────────

    def save_analysis(self, codes: list, results: dict, model: str = None) -> int:
        analyzed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 提取轻量摘要：名称列表 + 每只股票总分
        stock_results = results.get("results", [])
        names = [r.get("name") or r.get("code", "") for r in stock_results]
        scores_summary = []
        for r in stock_results:
            ts = r.get("total_score")
            if ts is None:
                sc = r.get("scores") or {}
                if sc:
                    ts = sum(v.get("score", 0) for v in sc.values() if isinstance(v, dict))
            scores_summary.append({
                "code": r.get("code", ""),
                "name": r.get("name", ""),
                "total_score": ts,
            })
        with self.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO stock_analysis (codes, names, scores_summary, results, model, analyzed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    json.dumps(codes, ensure_ascii=False),
                    json.dumps(names, ensure_ascii=False),
                    json.dumps(scores_summary, ensure_ascii=False),
                    json.dumps(results, ensure_ascii=False),
                    model,
                    analyzed_at,
                ),
            )
            return cur.lastrowid

    def list_analyses(self, date: str = None, limit: int = 20, offset: int = 0) -> dict:
        """返回历史分析列表（不含 results 大字段），支持日期筛选和分页"""
        where = "WHERE DATE(analyzed_at)=?" if date else ""
        params = [date] if date else []
        with self.get_conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM stock_analysis {where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT id, codes, names, scores_summary, model, analyzed_at FROM stock_analysis {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total}

    def get_analysis(self, analysis_id: int) -> Optional[dict]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM stock_analysis WHERE id=?", (analysis_id,)).fetchone()
        return dict(row) if row else None


db = StockAgentDB()  # 全局单例
