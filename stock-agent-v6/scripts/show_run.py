"""CLI：从 DB 读一次 run 的完整数据，渲染为 Markdown 输出到 stdout。

用法：
    python scripts/show_run.py              # 最新一条
    python scripts/show_run.py 42           # 指定 run_id
"""
import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from sqlalchemy import select  # noqa: E402

from db.engine import get_session  # noqa: E402
from db.models import (  # noqa: E402
    AgentOutput,
    ConditionScore,
    Run,
    SkepticFinding,
    StockDataEntry,
    StockRecommendation,
    Trigger,
)
from render.markdown_report import render_from_state  # noqa: E402
from schemas.research import ResearchReport, StockDataEntry as StockEntryModel  # noqa: E402
from schemas.screener import (  # noqa: E402
    ConditionScore as ScoreModel,
    ScreenerResult,
    StockRecommendation as RecModel,
)
from schemas.skeptic import SkepticFinding as FindingModel, SkepticResult  # noqa: E402
from schemas.supervisor import SupervisorDecision  # noqa: E402


def _rebuild_state(run_id: int) -> dict:
    """把 DB 里的数据拼回和 main.run() 产出同形的 state，交给 render_from_state。"""
    with get_session() as sess:
        run_row = sess.scalar(select(Run).where(Run.id == run_id))
        if run_row is None:
            raise SystemExit(f"run_id={run_id} not found")

        # Phase 6 后有两种关联：consumed_by_run_id（队列消费模式）或 run_id（旧直生模式）
        from sqlalchemy import or_
        trigger = sess.scalar(
            select(Trigger).where(
                or_(Trigger.consumed_by_run_id == run_id, Trigger.run_id == run_id)
            )
        )
        trigger_summary = {}
        if trigger:
            trigger_summary = {
                "trigger_id": trigger.trigger_id,
                "headline": trigger.headline,
                "industry": trigger.industry,
                "type": trigger.type,
                "strength": trigger.strength,
                "source": trigger.source,
                "published_at": str(trigger.published_at) if trigger.published_at else None,
                "summary": trigger.summary,
            }

        # ── Research：找到该 run 的 research agent_output，然后捞 stock_data_entries ──
        research_ao = sess.scalar(
            select(AgentOutput).where(
                AgentOutput.run_id == run_id,
                AgentOutput.agent_name == "research",
            )
        )
        research_report = None
        if research_ao:
            entries = sess.scalars(
                select(StockDataEntry).where(StockDataEntry.agent_output_id == research_ao.id)
            ).all()
            research_report = ResearchReport(
                trigger_ref=trigger_summary.get("trigger_id", "UNKNOWN"),
                candidates=[
                    StockEntryModel(
                        code=e.code, name=e.name, industry=e.industry,
                        leadership=e.leadership, holder_structure=e.holder_structure,
                        financial_summary=e.financial_summary,
                        technical_summary=e.technical_summary,
                        price_benefit=e.price_benefit,
                        data_gaps=json.loads(e.data_gaps_json) if e.data_gaps_json else [],
                        sources=json.loads(e.sources_json) if e.sources_json else [],
                    )
                    for e in entries
                ],
                overall_notes=research_ao.summary,
            )

        # ── Screener ──
        screener_ao = sess.scalar(
            select(AgentOutput).where(
                AgentOutput.run_id == run_id,
                AgentOutput.agent_name == "screener",
            )
        )
        screener_result = None
        if screener_ao:
            recs = sess.scalars(
                select(StockRecommendation)
                .where(StockRecommendation.agent_output_id == screener_ao.id)
                .order_by(StockRecommendation.rank)
            ).all()
            stock_models = []
            for rec in recs:
                scores = sess.scalars(
                    select(ConditionScore).where(ConditionScore.stock_recommendation_id == rec.id)
                ).all()
                stock_models.append(RecModel(
                    code=rec.code,
                    name=rec.name,
                    total_score=rec.total_score,
                    recommendation_level=rec.recommendation_level,
                    condition_scores=[
                        ScoreModel(
                            condition_id=s.condition_id,
                            condition_name=s.condition_name,
                            satisfaction=s.satisfaction,
                            weight=s.weight,
                            weighted_score=s.weighted_score,
                            reasoning=s.reasoning,
                        )
                        for s in scores
                    ],
                    data_gaps=json.loads(rec.data_gaps_json) if rec.data_gaps_json else [],
                    trigger_ref=rec.trigger_ref,
                    recommendation_rationale=rec.recommendation_rationale,
                    key_strengths=json.loads(rec.key_strengths_json) if rec.key_strengths_json else [],
                    key_risks=json.loads(rec.key_risks_json) if rec.key_risks_json else [],
                ))
            threshold = 0.65
            payload = screener_ao.payload_json
            if payload:
                try:
                    threshold = json.loads(payload).get("threshold_used", threshold)
                except Exception:
                    pass
            screener_result = ScreenerResult(
                stocks=stock_models,
                threshold_used=threshold,
                comparison_summary=screener_ao.summary,
            )

        # ── Skeptic ──
        skeptic_ao = sess.scalar(
            select(AgentOutput).where(
                AgentOutput.run_id == run_id,
                AgentOutput.agent_name == "skeptic",
            )
        )
        skeptic_result = None
        if skeptic_ao:
            findings = sess.scalars(
                select(SkepticFinding).where(SkepticFinding.agent_output_id == skeptic_ao.id)
            ).all()
            covered = []
            try:
                covered = json.loads(skeptic_ao.payload_json or "{}").get("covered_stocks", [])
            except Exception:
                pass
            skeptic_result = SkepticResult(
                findings=[
                    FindingModel(
                        stock_code=f.stock_code,
                        finding_type=f.finding_type,
                        content=f.content,
                    )
                    for f in findings
                ],
                covered_stocks=covered,
            )

        # ── Supervisor 的 finalize notes（供 markdown 末尾的综合判断使用）──
        final_supervisor = sess.scalar(
            select(AgentOutput)
            .where(
                AgentOutput.run_id == run_id,
                AgentOutput.agent_name == "supervisor",
            )
            .order_by(AgentOutput.sequence.desc())
        )
        last_decision = None
        if final_supervisor:
            try:
                payload = json.loads(final_supervisor.payload_json or "{}")
                last_decision = SupervisorDecision(
                    action=payload.get("action", "finalize"),
                    instructions=payload.get("instructions", "rebuilt from DB"),
                    round=final_supervisor.sequence if final_supervisor.sequence <= 4 else 4,
                    reasoning=final_supervisor.summary or "rebuilt",
                    notes=payload.get("notes"),
                )
            except Exception:
                pass

        # 统计 completed_steps（给 markdown 元信息用）
        all_aos = sess.scalars(
            select(AgentOutput).where(AgentOutput.run_id == run_id)
        ).all()
        completed_steps = []
        for ao in all_aos:
            completed_steps.append({"node": ao.agent_name, "round": ao.sequence})

        return {
            "trigger_summary": trigger_summary,
            "research_report": research_report,
            "screener_result": screener_result,
            "skeptic_result": skeptic_result,
            "last_decision": last_decision,
            "completed_steps": completed_steps,
            "run_started_at": str(run_row.started_at),
            "run_id": run_row.id,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", nargs="?", type=int, default=None,
                        help="要查看的 run_id；不传则取最新")
    args = parser.parse_args()

    if args.run_id is None:
        with get_session() as sess:
            latest = sess.scalar(select(Run).order_by(Run.id.desc()).limit(1))
        if latest is None:
            print("No runs in DB yet. Run main.py first.", file=sys.stderr)
            sys.exit(1)
        run_id = latest.id
    else:
        run_id = args.run_id

    state = _rebuild_state(run_id)
    print(render_from_state(state))


if __name__ == "__main__":
    main()
