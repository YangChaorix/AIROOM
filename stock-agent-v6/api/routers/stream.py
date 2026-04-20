"""全局 SSE 流：监听 system_logs + agent_outputs 新增事件。"""
import asyncio
import json

from fastapi import APIRouter
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from db.engine import get_session
from db.models import AgentOutput, SystemLog

router = APIRouter(prefix="/api", tags=["stream"])


@router.get("/stream")
async def global_stream():
    """前端用 EventSource('/api/stream') 监听；返回最新事件。"""
    async def gen():
        last_log_id = 0
        last_ao_id = 0
        # 启动时：只推送"此后新增"，先取当前最大 id 作为起点
        with get_session() as s:
            last_log = s.scalar(select(SystemLog).order_by(SystemLog.id.desc()).limit(1))
            if last_log:
                last_log_id = last_log.id
            last_ao = s.scalar(select(AgentOutput).order_by(AgentOutput.id.desc()).limit(1))
            if last_ao:
                last_ao_id = last_ao.id

        while True:
            with get_session() as s:
                # system_logs 新增
                new_logs = s.scalars(
                    select(SystemLog).where(SystemLog.id > last_log_id).order_by(SystemLog.id).limit(20)
                ).all()
                for log in new_logs:
                    last_log_id = log.id
                    yield {
                        "event": "log",
                        "data": json.dumps({
                            "id": log.id,
                            "level": log.level,
                            "source": log.source,
                            "message": log.message[:300],
                            "created_at": log.created_at.isoformat(),
                        }, ensure_ascii=False, default=str),
                    }

                # agent_outputs 新增
                new_aos = s.scalars(
                    select(AgentOutput).where(AgentOutput.id > last_ao_id).order_by(AgentOutput.id).limit(20)
                ).all()
                for ao in new_aos:
                    last_ao_id = ao.id
                    yield {
                        "event": "agent_output",
                        "data": json.dumps({
                            "id": ao.id,
                            "run_id": ao.run_id,
                            "agent": ao.agent_name,
                            "sequence": ao.sequence,
                            "summary": (ao.summary or "")[:200],
                            "created_at": ao.created_at.isoformat(),
                        }, ensure_ascii=False, default=str),
                    }

            # 心跳
            yield {"event": "heartbeat", "data": "{}"}
            await asyncio.sleep(2.0)

    return EventSourceResponse(gen())
