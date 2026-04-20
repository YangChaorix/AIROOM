"""推荐结果 API：按 trigger 分组的推荐股，供首页推荐模块使用。"""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from api.deps import get_db
from db.models import AgentOutput, ConditionScore, Run, SkepticFinding, StockRecommendation, Trigger

router = APIRouter(prefix="/api", tags=["recommendations"])


@router.get("/recommendations")
def list_recommendations(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """按 trigger 分组返回推荐股。
    - 只取 status=completed 的 run
    - 排除 trigger_key 以 stock: 开头的个股分析 run
    - 按 run.started_at 倒序（最新在前）
    """
    since = datetime.utcnow() - timedelta(days=days)

    runs = db.scalars(
        select(Run)
        .where(
            Run.status == "completed",
            Run.started_at >= since,
            or_(
                Run.trigger_key.is_(None),
                ~Run.trigger_key.like("stock:%"),
            ),
        )
        .order_by(Run.started_at.desc())
    ).all()

    groups: List[Dict[str, Any]] = []

    for run in runs:
        # 找 trigger
        trigger = db.scalar(
            select(Trigger).where(
                or_(Trigger.consumed_by_run_id == run.id, Trigger.run_id == run.id)
            )
        )

        # 找推荐股
        recs = db.scalars(
            select(StockRecommendation)
            .join(AgentOutput, StockRecommendation.agent_output_id == AgentOutput.id)
            .where(
                AgentOutput.run_id == run.id,
                StockRecommendation.recommendation_level != "skip",
            )
            .order_by(StockRecommendation.rank)
        ).all()

        if not recs:
            continue

        stocks_out = []
        for r in recs:
            findings = db.scalars(
                select(SkepticFinding).where(SkepticFinding.stock_recommendation_id == r.id)
            ).all()
            scores = db.scalars(
                select(ConditionScore).where(ConditionScore.stock_recommendation_id == r.id)
            ).all()
            stocks_out.append({
                "id": r.id,
                "code": r.code,
                "name": r.name,
                "level": r.recommendation_level,
                "rank": r.rank,
                "total_score": r.total_score,
                "recommendation_rationale": r.recommendation_rationale,
                "key_strengths": json.loads(r.key_strengths_json) if r.key_strengths_json else [],
                "key_risks": json.loads(r.key_risks_json) if r.key_risks_json else [],
                "data_gaps": json.loads(r.data_gaps_json) if r.data_gaps_json else [],
                "skeptic_findings": [
                    {"finding_type": f.finding_type, "content": f.content}
                    for f in findings
                ],
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
            })

        groups.append({
            "run_id": run.id,
            "run_started_at": run.started_at,
            "run_duration_ms": (
                int((run.finished_at - run.started_at).total_seconds() * 1000)
                if run.finished_at else None
            ),
            "trigger": {
                "id": trigger.id if trigger else None,
                "headline": trigger.headline if trigger else run.trigger_key,
                "type": trigger.type if trigger else "unknown",
                "industry": trigger.industry if trigger else None,
                "strength": trigger.strength if trigger else None,
                "priority": trigger.priority if trigger else None,
                "mode": trigger.mode if trigger else None,
                "summary": trigger.summary if trigger else None,
            } if trigger else {
                "id": None,
                "headline": run.trigger_key or "未知触发",
                "type": "unknown",
                "industry": None,
                "strength": None,
                "priority": None,
                "mode": None,
                "summary": None,
            },
            "stocks": stocks_out,
        })

    return groups
