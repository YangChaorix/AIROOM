"""Stock Agent v6 API — FastAPI 入口。

启动（开发）：
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

启动（生产，Docker）：
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1

路由见 api/routers/：
  - runs        /api/runs, /api/runs/:id, /api/runs/:id/stream
  - queue       /api/queue, /api/triggers, /api/queue/consume
  - stocks      /api/stock, /api/stocks/:code/history
  - conditions  /api/conditions (GET/PUT/POST)
  - channels    /api/channels, /api/channels/:name/run
  - prompts     /api/prompts/:agent (GET/POST/rollback/diff)
  - agents      /api/agents/status
  - logs        /api/logs
  - news        /api/news, /api/news/stats
  - stream      /api/stream  (全局 SSE)
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from api.routers import (  # noqa: E402
    agents,
    channels,
    conditions,
    logs,
    news,
    prompts,
    queue,
    runs,
    stocks,
    stream,
)

app = FastAPI(title="Stock Agent v6", version="0.6.0")

# CORS：开发时允许任意前端源（Vite 默认 5173）。生产（Docker 同源）可收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/healthz")
def healthz():
    return {"status": "ok", "version": "0.6.0"}


@app.get("/api/info")
def info():
    """系统总体信息：最近 run / 新闻数 / pending trigger 数。"""
    from sqlalchemy import func, select
    from db.engine import get_session
    from db.models import NewsItem, Run, Trigger

    with get_session() as s:
        total_runs = s.scalar(select(func.count(Run.id))) or 0
        latest_run = s.scalar(select(Run).order_by(Run.id.desc()).limit(1))
        news_total = s.scalar(select(func.count(NewsItem.id))) or 0
        pending = s.scalar(
            select(func.count(Trigger.id)).where(Trigger.status == "pending")
        ) or 0
        processing = s.scalar(
            select(func.count(Trigger.id)).where(Trigger.status == "processing")
        ) or 0
    return {
        "runs_total": total_runs,
        "latest_run_id": latest_run.id if latest_run else None,
        "latest_run_status": latest_run.status if latest_run else None,
        "news_total": news_total,
        "queue_pending": pending,
        "queue_processing": processing,
    }


# 挂载 10 个 router
for r in (runs, queue, stocks, conditions, channels, prompts, agents, logs, news, stream):
    app.include_router(r.router)


# 生产环境挂载静态文件（Docker 打包后 /app/api/static 是 React dist）
_STATIC_DIR = _ROOT / "api" / "static"
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="frontend")
