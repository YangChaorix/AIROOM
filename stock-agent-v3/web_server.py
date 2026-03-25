"""Stock Agent Dashboard - Web Server v1.0"""
import sqlite3
import json
import logging
import os
import threading
import subprocess
import sys
from datetime import datetime
from typing import Optional

import hmac
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException, Body, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "db", "stock_agent.db")
WEB_DIR = os.path.join(BASE_DIR, "web")

sys.path.insert(0, BASE_DIR)

# ── 日志初始化（与 main.py 保持一致，支持 LOG_LEVEL / LOG_FILE_ENABLED 环境变量）──
def _setup_logging():
    from dotenv import load_dotenv
    load_dotenv()
    log_file_enabled = os.getenv("LOG_FILE_ENABLED", "true").lower() != "false"
    console_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter(fmt, datefmt))
    root.addHandler(ch)
    if log_file_enabled:
        log_dir = os.path.join(BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{datetime.now().strftime('%Y-%m-%d')}.log")
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(fmt, datefmt))
        root.addHandler(fh)
    for noisy in ["httpx", "httpcore", "urllib3", "asyncio", "uvicorn.access"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

_setup_logging()
logger = logging.getLogger(__name__)

from tools.db import db as agent_db  # noqa: E402

# ── 认证配置 ───────────────────────────────────────────────────────────────────
_WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
_WEB_PASSWORD = os.getenv("WEB_PASSWORD", "admin123")
_TOKEN_SECRET  = os.getenv("WEB_TOKEN_SECRET", "stock-agent-secret-2026")

def _make_token(username: str, password: str) -> str:
    raw = f"{username}:{password}:{_TOKEN_SECRET}"
    return hmac.new(raw.encode(), _TOKEN_SECRET.encode(), hashlib.sha256).hexdigest()

_VALID_TOKEN = _make_token(_WEB_USERNAME, _WEB_PASSWORD)

def _check_auth(request: Request):
    token = request.headers.get("X-Auth-Token", "")
    if token != _VALID_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

AUTH = Depends(_check_auth)

# ── Manual Run State ──────────────────────────────────────────────────────────
_run_state = {"running": False, "started_at": None, "finished_at": None, "status": "idle", "error": None}
_collect_state = {"running": False, "started_at": None, "finished_at": None, "status": "idle", "error": None}


@asynccontextmanager
async def lifespan(app):
    """启动时清理上次异常退出留下的 running 状态"""
    if os.path.exists(DB_PATH):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "UPDATE run_logs SET status='interrupted', finished_at=? WHERE status='running'",
                (datetime.now().isoformat(timespec="seconds"),),
            )
    yield


app = FastAPI(title="Stock Agent Dashboard", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def parse_json_fields(d: dict) -> dict:
    for k, v in d.items():
        if isinstance(v, str) and v and v[0] in "[{":
            try:
                d[k] = json.loads(v)
            except Exception:
                pass
    return d


def query_db(sql: str, params=(), fetchall=True):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=503, detail=f"Database not found: {DB_PATH}")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        if fetchall:
            rows = cur.fetchall()
            return [parse_json_fields(dict(r)) for r in rows]
        else:
            row = cur.fetchone()
            return parse_json_fields(dict(row)) if row else None


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def api_health():
    return {"status": "ok"}


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/api/login")
def api_login(body: dict = Body(...)):
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    if username == _WEB_USERNAME and password == _WEB_PASSWORD:
        return {"token": _VALID_TOKEN}
    raise HTTPException(status_code=401, detail="用户名或密码错误")


# ── Static ────────────────────────────────────────────────────────────────────
@app.get("/")
def serve_index():
    p = os.path.join(WEB_DIR, "index.html")
    if not os.path.exists(p):
        raise HTTPException(404, "Frontend not found")
    return FileResponse(p)


# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/api/summary", dependencies=[AUTH])
def api_summary():
    if not os.path.exists(DB_PATH):
        return {"error": "Database not found"}

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        total_runs    = c.execute("SELECT COUNT(*) FROM run_logs").fetchone()[0]
        total_triggers= c.execute("SELECT COUNT(*) FROM triggers").fetchone()[0]
        total_stocks  = c.execute("SELECT COUNT(*) FROM screener_stocks").fetchone()[0]
        total_news    = c.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]

        today = c.execute("""
            SELECT MAX(d) FROM (
                SELECT run_date AS d FROM run_logs
                UNION SELECT run_date FROM triggers
                UNION SELECT run_date FROM screener_stocks
                UNION SELECT run_date FROM review_reports
                UNION SELECT collect_date FROM news_items
            )
        """).fetchone()[0]

        today_data = {"date": today, "runs": 0, "triggers": 0, "stocks": 0, "news": 0}
        latest_review = None

        if today:
            today_data["runs"]     = c.execute("SELECT COUNT(*) FROM run_logs WHERE run_date=?", (today,)).fetchone()[0]
            today_data["triggers"] = c.execute("SELECT COUNT(*) FROM triggers WHERE run_date=?", (today,)).fetchone()[0]
            today_data["stocks"]   = c.execute("SELECT COUNT(*) FROM screener_stocks WHERE run_date=?", (today,)).fetchone()[0]
            today_data["news"]     = c.execute("SELECT COUNT(*) FROM news_items WHERE collect_date=?", (today,)).fetchone()[0]

            row = c.execute(
                "SELECT market_up_count, market_down_count, avg_pct_change, market_sentiment FROM review_reports WHERE run_date=?",
                (today,)
            ).fetchone()
            if row:
                latest_review = {"up": row[0], "down": row[1], "avg_change": row[2], "sentiment": row[3]}

        # Last 14 days trigger activity
        recent_triggers = c.execute("""
            SELECT run_date, COUNT(*) as cnt FROM triggers
            WHERE run_date >= date('now', '-14 days')
            GROUP BY run_date ORDER BY run_date
        """).fetchall()

        # News sources (today)
        news_sources = []
        if today:
            src_rows = c.execute("""
                SELECT source, COUNT(*) as cnt FROM news_items
                WHERE collect_date=? GROUP BY source ORDER BY cnt DESC
            """, (today,)).fetchall()
            news_sources = [{"source": r[0], "count": r[1]} for r in src_rows]

        # Strength distribution (latest date)
        strength_dist = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        if today:
            sd = c.execute("SELECT strength, COUNT(*) FROM triggers WHERE run_date=? GROUP BY strength", (today,)).fetchall()
            for r in sd:
                if r[0]:
                    strength_dist[r[0]] = r[1]

        # Last 5 runs
        last_runs = c.execute("""
            SELECT run_date, run_mode, started_at, finished_at, status, error_msg
            FROM run_logs ORDER BY started_at DESC LIMIT 5
        """).fetchall()

        return {
            "latest_date": today,
            "totals": {"runs": total_runs, "triggers": total_triggers, "stocks": total_stocks, "news": total_news},
            "today": today_data,
            "latest_review": latest_review,
            "recent_trigger_activity": [{"date": r[0], "count": r[1]} for r in recent_triggers],
            "news_sources": news_sources,
            "strength_distribution": strength_dist,
            "last_runs": [
                {"run_date": r[0], "run_mode": r[1], "started_at": r[2],
                 "finished_at": r[3], "status": r[4], "error_msg": r[5]}
                for r in last_runs
            ],
        }


# ── Dates ─────────────────────────────────────────────────────────────────────
@app.get("/api/dates", dependencies=[AUTH])
def api_dates():
    rows = query_db("""
        SELECT DISTINCT d FROM (
            SELECT run_date AS d FROM run_logs
            UNION SELECT run_date FROM triggers
            UNION SELECT run_date FROM screener_stocks
            UNION SELECT run_date FROM review_reports
            UNION SELECT collect_date FROM news_items
        ) ORDER BY d DESC LIMIT 60
    """)
    return {"dates": [r["d"] for r in rows if r["d"]]}


# ── Run Logs ──────────────────────────────────────────────────────────────────
@app.get("/api/run-logs", dependencies=[AUTH])
def api_run_logs(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    rows = query_db("SELECT * FROM run_logs ORDER BY started_at DESC LIMIT ? OFFSET ?", (limit, offset))
    total = query_db("SELECT COUNT(*) as cnt FROM run_logs", fetchall=False)
    return {"items": rows, "total": total["cnt"] if total else 0}


# ── Triggers ──────────────────────────────────────────────────────────────────
@app.get("/api/triggers", dependencies=[AUTH])
def api_triggers(date: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500)):
    if date:
        rows = query_db("SELECT * FROM triggers WHERE run_date=? ORDER BY trigger_index", (date,))
    else:
        rows = query_db("SELECT * FROM triggers ORDER BY run_date DESC, trigger_index LIMIT ?", (limit,))
    return {"items": rows}


# ── Screener Stocks ───────────────────────────────────────────────────────────
@app.get("/api/screener-stocks/runs", dependencies=[AUTH])
def api_screener_runs(date: Optional[str] = Query(None)):
    if not date:
        raise HTTPException(400, "date is required")
    rows = query_db(
        "SELECT DISTINCT run_id FROM screener_stocks WHERE run_date=? AND run_id!='' ORDER BY run_id DESC",
        (date,),
    )
    return {"runs": [r["run_id"] for r in rows]}


@app.get("/api/screener-stocks", dependencies=[AUTH])
def api_screener_stocks(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    if date:
        if run_id:
            rows = query_db(
                "SELECT * FROM screener_stocks WHERE run_date=? AND run_id=? ORDER BY rank LIMIT ?",
                (date, run_id, limit),
            )
        else:
            # 取最新批次
            latest = query_db(
                "SELECT run_id FROM screener_stocks WHERE run_date=? ORDER BY run_id DESC LIMIT 1",
                (date,), fetchall=False,
            )
            if not latest:
                return {"items": [], "run_id": None}
            rows = query_db(
                "SELECT * FROM screener_stocks WHERE run_date=? AND run_id=? ORDER BY rank LIMIT ?",
                (date, latest["run_id"], limit),
            )
            run_id = latest["run_id"]
    else:
        rows = query_db("SELECT * FROM screener_stocks ORDER BY run_date DESC, run_id DESC, rank LIMIT ?", (limit,))
    return {"items": rows, "run_id": run_id}


# ── Review ────────────────────────────────────────────────────────────────────
@app.get("/api/review-report", dependencies=[AUTH])
def api_review_report(date: Optional[str] = Query(None)):
    if date:
        return query_db("SELECT * FROM review_reports WHERE run_date=?", (date,), fetchall=False) or {}
    return query_db("SELECT * FROM review_reports ORDER BY run_date DESC LIMIT 1", fetchall=False) or {}


@app.get("/api/review-reports", dependencies=[AUTH])
def api_review_reports(limit: int = Query(30, ge=1, le=100)):
    rows = query_db("""
        SELECT id, run_date, market_up_count, market_down_count,
               avg_pct_change, market_sentiment, top_sectors, is_friday, created_at
        FROM review_reports ORDER BY run_date DESC LIMIT ?
    """, (limit,))
    return {"items": rows}


# ── News ──────────────────────────────────────────────────────────────────────
@app.get("/api/news", dependencies=[AUTH])
def api_news(
    date: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    time_start: Optional[str] = Query(None),
    time_end: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    conditions, params = [], []
    if date:
        conditions.append("collect_date=?"); params.append(date)
    if source:
        conditions.append("source=?"); params.append(source)
    if priority:
        conditions.append("priority=?"); params.append(priority)
    if time_start:
        conditions.append("COALESCE(time(pub_time), time(collected_at)) >= time(?)")
        params.append(time_start)
    if time_end:
        conditions.append("COALESCE(time(pub_time), time(collected_at)) <= time(?)")
        params.append(time_end)
    if q:
        conditions.append("(title LIKE ? OR content LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = query_db(
        f"SELECT id, collect_date, title, content, source, pub_time, collected_at, priority FROM news_items {where} ORDER BY COALESCE(pub_time, collected_at) DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    total = query_db(f"SELECT COUNT(*) as cnt FROM news_items {where}", params, fetchall=False)
    return {"items": rows, "total": total["cnt"] if total else 0}


@app.get("/api/news/sources", dependencies=[AUTH])
def api_news_sources(date: Optional[str] = Query(None)):
    if date:
        rows = query_db("SELECT DISTINCT source FROM news_items WHERE collect_date=? ORDER BY source", (date,))
    else:
        rows = query_db("SELECT DISTINCT source FROM news_items ORDER BY source")
    return {"sources": [r["source"] for r in rows if r["source"]]}


# ── Event History ─────────────────────────────────────────────────────────────
@app.get("/api/event-history", dependencies=[AUTH])
def api_event_history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    rows = query_db("SELECT * FROM event_history ORDER BY last_seen DESC LIMIT ? OFFSET ?", (limit, offset))
    total = query_db("SELECT COUNT(*) as cnt FROM event_history", fetchall=False)
    return {"items": rows, "total": total["cnt"] if total else 0}


# ── Prompts ───────────────────────────────────────────────────────────────────
@app.get("/api/prompts", dependencies=[AUTH])
def api_prompts():
    rows = query_db("""
        SELECT id, agent_name, prompt_name, version, is_active, created_at, note,
               LENGTH(content) as content_length
        FROM prompts ORDER BY agent_name, is_active DESC, created_at DESC
    """)
    return {"items": rows}


@app.get("/api/prompts/{prompt_id}", dependencies=[AUTH])
def api_prompt_detail(prompt_id: int):
    row = query_db("SELECT * FROM prompts WHERE id=?", (prompt_id,), fetchall=False)
    if not row:
        raise HTTPException(404, "Prompt not found")
    return row


@app.post("/api/prompts", dependencies=[AUTH])
def api_create_prompt(payload: dict = Body(...)):
    agent_name  = (payload.get("agent_name") or "").strip()
    prompt_name = (payload.get("prompt_name") or "").strip()
    content     = (payload.get("content") or "").strip()
    note        = (payload.get("note") or "").strip()
    if not agent_name or not prompt_name or not content:
        raise HTTPException(400, "agent_name, prompt_name, content are required")
    if agent_name not in ("trigger", "screener", "review"):
        raise HTTPException(400, f"Unknown agent: {agent_name}")
    new_id = agent_db.save_prompt(agent_name, prompt_name, content, note=note)
    return query_db("SELECT * FROM prompts WHERE id=?", (new_id,), fetchall=False)


@app.post("/api/prompts/{prompt_id}/activate", dependencies=[AUTH])
def api_activate_prompt(prompt_id: int):
    ok = agent_db.activate_prompt(prompt_id)
    if not ok:
        raise HTTPException(404, f"Prompt {prompt_id} not found")
    return query_db("SELECT * FROM prompts WHERE id=?", (prompt_id,), fetchall=False)


# ── System Config ─────────────────────────────────────────────────────────────
@app.get("/api/config", dependencies=[AUTH])
def api_get_configs():
    return {"items": agent_db.get_all_configs()}


@app.put("/api/config/{key}", dependencies=[AUTH])
def api_set_config(key: str, payload: dict = Body(...)):
    value = payload.get("value")
    if value is None:
        raise HTTPException(400, "value is required")
    ok = agent_db.set_config(key, str(value))
    if not ok:
        raise HTTPException(404, f"Config key '{key}' not found")
    return {"key": key, "value": str(value)}


# ── Stock Analysis ────────────────────────────────────────────────────────────
@app.post("/api/analyze-stocks", dependencies=[AUTH])
def api_analyze_stocks(payload: dict = Body(...)):
    codes_raw = payload.get("codes", [])
    if not codes_raw or len(codes_raw) > 5:
        raise HTTPException(400, "请提供 1-5 个股票代码")
    codes = [c.strip().zfill(6) for c in codes_raw if c.strip()]
    if not codes:
        raise HTTPException(400, "股票代码无效")
    from agents.stock_analyst_agent import run_stock_analyst
    result = run_stock_analyst(codes)
    analysis_id = agent_db.save_analysis(codes, result, model=result.get("model"))
    result["id"] = analysis_id
    return result


@app.get("/api/analyses", dependencies=[AUTH])
def api_list_analyses(
    date: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return agent_db.list_analyses(date=date, limit=limit, offset=offset)


@app.get("/api/analyses/{analysis_id}", dependencies=[AUTH])
def api_get_analysis(analysis_id: int):
    row = agent_db.get_analysis(analysis_id)
    if not row:
        raise HTTPException(404, "Not found")
    row["results"] = json.loads(row["results"])
    row["codes"] = json.loads(row["codes"])
    return row


# ── Manual Run ────────────────────────────────────────────────────────────────
def _do_run():
    _run_state["running"] = True
    _run_state["started_at"] = datetime.now().isoformat(timespec="seconds")
    _run_state["finished_at"] = None
    _run_state["error"] = None
    _run_state["status"] = "running"
    try:
        main_py = os.path.join(BASE_DIR, "main.py")
        result = subprocess.run(
            [sys.executable, main_py, "--event"],
            capture_output=True, text=True, cwd=BASE_DIR
        )
        if result.returncode == 0:
            _run_state["status"] = "success"
        else:
            _run_state["status"] = "error"
            _run_state["error"] = (result.stderr or result.stdout or "Unknown error")[-500:]
    except Exception as e:
        _run_state["status"] = "error"
        _run_state["error"] = str(e)
    finally:
        _run_state["running"] = False
        _run_state["finished_at"] = datetime.now().isoformat(timespec="seconds")


@app.post("/api/run/trigger", dependencies=[AUTH])
def api_run_trigger():
    if _run_state["running"]:
        raise HTTPException(status_code=409, detail="Analysis already running")
    t = threading.Thread(target=_do_run, daemon=True)
    t.start()
    return {"message": "Analysis started", "started_at": _run_state["started_at"]}


@app.get("/api/run/status", dependencies=[AUTH])
def api_run_status():
    return dict(_run_state)


def _do_collect():
    _collect_state["running"] = True
    _collect_state["started_at"] = datetime.now().isoformat(timespec="seconds")
    _collect_state["finished_at"] = None
    _collect_state["error"] = None
    _collect_state["status"] = "running"
    try:
        main_py = os.path.join(BASE_DIR, "main.py")
        result = subprocess.run(
            [sys.executable, main_py, "--collect"],
            capture_output=True, text=True, cwd=BASE_DIR
        )
        if result.returncode == 0:
            _collect_state["status"] = "success"
        else:
            _collect_state["status"] = "error"
            _collect_state["error"] = (result.stderr or result.stdout or "Unknown error")[-500:]
    except Exception as e:
        _collect_state["status"] = "error"
        _collect_state["error"] = str(e)
    finally:
        _collect_state["running"] = False
        _collect_state["finished_at"] = datetime.now().isoformat(timespec="seconds")


@app.post("/api/news/collect", dependencies=[AUTH])
def api_news_collect():
    if _collect_state["running"]:
        raise HTTPException(status_code=409, detail="News collection already running")
    t = threading.Thread(target=_do_collect, daemon=True)
    t.start()
    return {"message": "News collection started", "started_at": _collect_state["started_at"]}


@app.get("/api/news/collect/status", dependencies=[AUTH])
def api_news_collect_status():
    return dict(_collect_state)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"📊 Stock Agent Dashboard  →  http://localhost:8888")
    print(f"   Database: {DB_PATH}")
    uvicorn.run("web_server:app", host="0.0.0.0", port=8888, reload=True)
