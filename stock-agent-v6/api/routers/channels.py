"""新闻渠道 API：读写 news_channels.json + 立即抓取。"""
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/api", tags=["channels"])

_ROOT = Path(__file__).parent.parent.parent
_CHANNELS_PATH = _ROOT / "config" / "news_channels.json"


def _load_cfg() -> Dict[str, Any]:
    return json.loads(_CHANNELS_PATH.read_text(encoding="utf-8"))


def _save_cfg(cfg: Dict[str, Any]) -> None:
    _CHANNELS_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@router.get("/channels")
def list_channels():
    cfg = _load_cfg()
    return {
        "timezone": cfg.get("_timezone", "Asia/Shanghai"),
        "channels": cfg.get("channels", []),
    }


@router.put("/channels/{name}")
def update_channel(name: str, payload: Dict[str, Any] = Body(...)):
    """改启用 / cron / source_label / adapter 等字段。"""
    cfg = _load_cfg()
    channels = cfg.get("channels", [])
    target = next((c for c in channels if c.get("name") == name), None)
    if not target:
        raise HTTPException(404, f"channel {name} not found")
    for k, v in payload.items():
        if k.startswith("_"):
            continue
        target[k] = v
    _save_cfg(cfg)
    return {"status": "ok", "channel": target}


@router.post("/channels/{name}/run")
def run_channel_now(name: str):
    """立即抓一次（调 scheduler --once）。"""
    proc = subprocess.Popen(
        [sys.executable, "scheduler/run.py", "--once", name],
        cwd=str(_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return {"status": "started", "pid": proc.pid, "channel": name}


@router.post("/channels/run-all")
def run_all_channels():
    """立即抓取所有启用的渠道。子进程异步跑，不阻塞。

    去重由 news_items.content_hash 唯一约束保证，重复点击只会多一次空跑。
    """
    proc = subprocess.Popen(
        [sys.executable, "scheduler/run.py", "--once", "channels"],
        cwd=str(_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    cfg = _load_cfg()
    enabled = [c["name"] for c in cfg.get("channels", []) if c.get("enabled", True)]
    return {"status": "started", "pid": proc.pid, "channels": enabled}
