"""runs 相关 API：列表、详情、进行中 run 的 SSE 流。"""
import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from api.deps import get_db
from db.models import (
    AgentOutput,
    ConditionScore,
    Run,
    SkepticFinding,
    StockDataEntry,
    StockRecommendation,
    ToolCall,
    Trigger,
)

router = APIRouter(prefix="/api", tags=["runs"])


def _run_duration_ms(r: Run) -> Optional[int]:
    if r.finished_at and r.started_at:
        return int((r.finished_at - r.started_at).total_seconds() * 1000)
    return None


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    """最近 N 条 run。"""
    rows = db.scalars(select(Run).order_by(Run.started_at.desc()).limit(limit)).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "trigger_key": r.trigger_key,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "duration_ms": _run_duration_ms(r),
            "error": r.error,
        }
        for r in rows
    ]


@router.get("/runs/{run_id}")
def get_run_detail(run_id: int, db: Session = Depends(get_db)):
    """某 run 的完整链路：trigger + timeline + recommendations + skeptic。"""
    run = db.scalar(select(Run).where(Run.id == run_id))
    if not run:
        raise HTTPException(404, f"run {run_id} not found")

    # Trigger：兼容 consumed_by_run_id（Phase 6）和 run_id（遗留）
    from sqlalchemy import or_
    trigger = db.scalar(
        select(Trigger).where(
            or_(Trigger.consumed_by_run_id == run_id, Trigger.run_id == run_id)
        )
    )

    # Agent timeline
    agent_outputs = db.scalars(
        select(AgentOutput)
        .where(AgentOutput.run_id == run_id)
        .order_by(AgentOutput.id)
    ).all()

    timeline: List[Dict[str, Any]] = []
    for ao in agent_outputs:
        payload = json.loads(ao.payload_json) if ao.payload_json else {}
        metrics = json.loads(ao.metrics_json) if ao.metrics_json else {}
        node: Dict[str, Any] = {
            "id": ao.id,
            "agent": ao.agent_name,
            "sequence": ao.sequence,
            "status": ao.status,
            "summary": ao.summary,
            "payload": payload,
            "metrics": metrics,
            "created_at": ao.created_at,
        }
        # Research 节点附 tool_calls
        if ao.agent_name == "research":
            tcs = db.scalars(
                select(ToolCall)
                .where(ToolCall.agent_output_id == ao.id)
                .order_by(ToolCall.sequence)
            ).all()
            node["tool_calls"] = [
                {
                    "sequence": tc.sequence,
                    "tool_name": tc.tool_name,
                    "args": json.loads(tc.args_json) if tc.args_json else {},
                    "stock_code": tc.stock_code,
                    "latency_ms": tc.latency_ms,
                    "error": tc.error,
                    "result_preview": tc.result_preview,
                }
                for tc in tcs
            ]
        timeline.append(node)

    # Recommendations（来自 Screener）
    recs_rows = db.scalars(
        select(StockRecommendation)
        .join(AgentOutput, StockRecommendation.agent_output_id == AgentOutput.id)
        .where(AgentOutput.run_id == run_id)
        .order_by(StockRecommendation.rank)
    ).all()

    recommendations: List[Dict[str, Any]] = []
    for r in recs_rows:
        scores = db.scalars(
            select(ConditionScore).where(ConditionScore.stock_recommendation_id == r.id)
        ).all()
        findings = db.scalars(
            select(SkepticFinding).where(SkepticFinding.stock_recommendation_id == r.id)
        ).all()
        recommendations.append({
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "total_score": r.total_score,
            "level": r.recommendation_level,
            "rank": r.rank,
            "recommendation_rationale": r.recommendation_rationale,
            "key_strengths": json.loads(r.key_strengths_json) if r.key_strengths_json else [],
            "key_risks": json.loads(r.key_risks_json) if r.key_risks_json else [],
            "data_gaps": json.loads(r.data_gaps_json) if r.data_gaps_json else [],
            "trigger_ref": r.trigger_ref,
            "condition_scores": [
                {
                    "condition_id": s.condition_id,
                    "condition_name": s.condition_name,
                    "satisfaction": s.satisfaction,
                    "weight": s.weight,
                    "weighted_score": s.weighted_score,
                    "reasoning": s.reasoning,
                }
                for s in scores
            ],
            "skeptic_findings": [
                {"finding_type": f.finding_type, "content": f.content}
                for f in findings
            ],
        })

    # 横向对比（Screener agent_output.summary）
    screener_ao = next((ao for ao in agent_outputs if ao.agent_name == "screener"), None)
    comparison_summary = screener_ao.summary if screener_ao else None

    # Supervisor 综合判断（action=finalize 那一条的 notes）
    supervisor_notes = None
    for ao in reversed(agent_outputs):
        if ao.agent_name == "supervisor" and ao.payload_json:
            try:
                p = json.loads(ao.payload_json)
                if p.get("action") == "finalize":
                    supervisor_notes = p.get("notes")
                    break
            except Exception:
                pass

    return {
        "run_id": run.id,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": _run_duration_ms(run),
        "trigger_key": run.trigger_key,
        "error": run.error,
        "trigger": {
            "id": trigger.id,
            "trigger_id": trigger.trigger_id,
            "headline": trigger.headline,
            "industry": trigger.industry,
            "type": trigger.type,
            "strength": trigger.strength,
            "priority": trigger.priority,
            "source": trigger.source,
            "mode": trigger.mode,
            "summary": trigger.summary,
            "source_news_ids": json.loads(trigger.source_news_ids) if trigger.source_news_ids else [],
            "metadata": json.loads(trigger.metadata_json) if trigger.metadata_json else {},
        } if trigger else None,
        "timeline": timeline,
        "recommendations": recommendations,
        "comparison_summary": comparison_summary,
        "supervisor_notes": supervisor_notes,
    }


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int, db: Session = Depends(get_db)):
    """SSE：轮询该 run 的 agent_outputs + tool_calls 新增，推送新事件。

    前端用 EventSource 监听，直到 run.status != 'running'。
    """
    async def event_generator():
        last_agent_output_id = 0
        last_tool_call_id = 0

        while True:
            # 每次重开 session（避免长连接共享 session）
            from db.engine import get_session
            with get_session() as s:
                run = s.scalar(select(Run).where(Run.id == run_id))
                if not run:
                    yield {"event": "error", "data": json.dumps({"error": f"run {run_id} not found"})}
                    return

                # 新增 agent_outputs
                new_aos = s.scalars(
                    select(AgentOutput)
                    .where(AgentOutput.run_id == run_id, AgentOutput.id > last_agent_output_id)
                    .order_by(AgentOutput.id)
                ).all()
                for ao in new_aos:
                    last_agent_output_id = ao.id
                    yield {
                        "event": "agent_output",
                        "data": json.dumps({
                            "id": ao.id,
                            "agent": ao.agent_name,
                            "sequence": ao.sequence,
                            "summary": ao.summary,
                            "created_at": ao.created_at.isoformat(),
                        }, ensure_ascii=False, default=str),
                    }

                # 新增 tool_calls
                new_tcs = s.scalars(
                    select(ToolCall)
                    .join(AgentOutput, ToolCall.agent_output_id == AgentOutput.id)
                    .where(AgentOutput.run_id == run_id, ToolCall.id > last_tool_call_id)
                    .order_by(ToolCall.id)
                ).all()
                for tc in new_tcs:
                    last_tool_call_id = tc.id
                    yield {
                        "event": "tool_call",
                        "data": json.dumps({
                            "id": tc.id,
                            "tool_name": tc.tool_name,
                            "stock_code": tc.stock_code,
                            "latency_ms": tc.latency_ms,
                            "error": tc.error,
                        }, ensure_ascii=False),
                    }

                # 完成就停
                if run.status in ("completed", "failed"):
                    yield {
                        "event": "run_end",
                        "data": json.dumps({"run_id": run_id, "status": run.status}),
                    }
                    return

            await asyncio.sleep(1.5)

    return EventSourceResponse(event_generator())
