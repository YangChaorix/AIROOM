"""推荐结果 API：按 trigger 分组的推荐股，供首页推荐模块使用。"""
import json
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
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
    - 每只股票附带 `supporting_triggers`：同一日期范围内**其他 trigger** 也推荐了该股的清单（用于前端展示"多 trigger 共振"）
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

    if not runs:
        return []

    run_ids = [r.id for r in runs]

    # 预取：run_id -> trigger（可能为空）
    run_to_trigger: Dict[int, Trigger] = {}
    triggers_all = db.scalars(
        select(Trigger).where(
            or_(
                Trigger.consumed_by_run_id.in_(run_ids),
                Trigger.run_id.in_(run_ids),
            )
        )
    ).all()
    for t in triggers_all:
        if t.consumed_by_run_id in run_ids:
            run_to_trigger[t.consumed_by_run_id] = t
        elif t.run_id in run_ids:
            run_to_trigger.setdefault(t.run_id, t)

    # 预取：本日期范围内所有推荐股（用于跨 trigger 聚合）
    all_recs = db.scalars(
        select(StockRecommendation)
        .join(AgentOutput, StockRecommendation.agent_output_id == AgentOutput.id)
        .where(
            AgentOutput.run_id.in_(run_ids),
            StockRecommendation.recommendation_level != "skip",
        )
    ).all()

    # 按 run_id 分组
    recs_by_run: Dict[int, List[StockRecommendation]] = defaultdict(list)
    # 按 code 分组，用于跨 trigger 聚合
    code_to_trigger_refs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    # rec.id -> run_id 反查（需用 agent_output.run_id 回填）
    agent_output_run_map: Dict[int, int] = {}
    ao_rows = db.execute(
        select(AgentOutput.id, AgentOutput.run_id).where(AgentOutput.run_id.in_(run_ids))
    ).all()
    for ao_id, ao_run_id in ao_rows:
        agent_output_run_map[ao_id] = ao_run_id

    for r in all_recs:
        run_id = agent_output_run_map.get(r.agent_output_id)
        if run_id is None:
            continue
        recs_by_run[run_id].append(r)
        t = run_to_trigger.get(run_id)
        if t and t.type != "individual_stock_analysis":
            code_to_trigger_refs[r.code].append({
                "run_id": run_id,
                "trigger_id": t.trigger_id,
                "headline": t.headline,
                "industry": t.industry,
                "type": t.type,
                "strength": t.strength,
            })

    groups: List[Dict[str, Any]] = []

    for run in runs:
        trigger = run_to_trigger.get(run.id)
        recs = sorted(recs_by_run.get(run.id, []), key=lambda x: (x.rank or 999))
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

            # 跨 trigger 共振：同日期范围内其他 trigger 也推荐了这只股
            supporting = [
                ref for ref in code_to_trigger_refs.get(r.code, [])
                if ref["run_id"] != run.id
            ]

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
                "supporting_triggers": supporting,
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
