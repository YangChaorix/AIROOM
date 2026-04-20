"""create views v_recommendation_trace and v_stock_analysis_history

Revision ID: 95ebdbf32364
Revises: 3b97032df62f
Create Date: 2026-04-19 10:27:04.315543

两个链路追溯视图——Alembic autogenerate 不支持 VIEW，手写 CREATE/DROP。
定义详见 docs/PHASE3_DB_PLAN.md §3.9 和 §4·2。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "95ebdbf32364"
down_revision: Union[str, Sequence[str], None] = "3b97032df62f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_V_RECOMMENDATION_TRACE = """
CREATE VIEW v_recommendation_trace AS
SELECT
  r.id AS rec_id,
  r.code, r.name, r.total_score, r.recommendation_level AS level, r.rank,
  r.recommendation_rationale, r.key_strengths_json, r.key_risks_json,
  ao_screener.summary AS comparison_summary,
  ao_screener.run_id,
  t.trigger_id, t.headline AS trigger_headline, t.industry AS trigger_industry,
  t.strength AS trigger_strength, t.mode AS trigger_mode,
  sde.leadership, sde.financial_summary, sde.holder_structure,
  sde.technical_summary, sde.price_benefit, sde.data_gaps_json AS research_data_gaps,
  (SELECT json_group_array(json_object(
    'condition_id', cs.condition_id, 'satisfaction', cs.satisfaction,
    'weight', cs.weight, 'weighted_score', cs.weighted_score, 'reasoning', cs.reasoning))
   FROM condition_scores cs WHERE cs.stock_recommendation_id = r.id) AS condition_scores_json,
  (SELECT json_group_array(json_object(
    'finding_type', sf.finding_type, 'content', sf.content))
   FROM skeptic_findings sf WHERE sf.stock_recommendation_id = r.id) AS skeptic_findings_json,
  (SELECT json_group_array(json_object(
    'sequence', tc.sequence, 'tool', tc.tool_name, 'latency_ms', tc.latency_ms, 'error', tc.error))
   FROM tool_calls tc
   WHERE tc.stock_code = r.code AND tc.agent_output_id = sde.agent_output_id) AS tool_calls_json,
  (SELECT json_extract(ao.payload_json, '$.notes') FROM agent_outputs ao
   WHERE ao.run_id = ao_screener.run_id
     AND ao.agent_name = 'supervisor'
     AND json_extract(ao.payload_json, '$.action') = 'finalize'
   LIMIT 1) AS supervisor_notes,
  r.created_at AS rec_created_at
FROM stock_recommendations r
JOIN agent_outputs ao_screener
  ON ao_screener.id = r.agent_output_id AND ao_screener.agent_name = 'screener'
LEFT JOIN triggers t ON t.run_id = ao_screener.run_id
LEFT JOIN stock_data_entries sde ON sde.id = r.stock_data_entry_id;
"""

_V_STOCK_ANALYSIS_HISTORY = """
CREATE VIEW v_stock_analysis_history AS
SELECT
  r.code, r.name,
  r.total_score, r.recommendation_level, r.rank,
  r.recommendation_rationale, r.key_strengths_json, r.key_risks_json,
  t.type AS analysis_type,
  t.headline AS trigger_headline,
  t.industry AS trigger_industry,
  CASE
    WHEN t.type = 'individual_stock_analysis'
         AND json_extract(t.metadata_json, '$.focus_primary') = r.code
      THEN 'primary'
    WHEN t.type = 'individual_stock_analysis'
      THEN 'peer'
    ELSE 'candidate'
  END AS role,
  ao_screener.run_id,
  r.created_at
FROM stock_recommendations r
JOIN agent_outputs ao_screener
  ON ao_screener.id = r.agent_output_id AND ao_screener.agent_name = 'screener'
JOIN triggers t ON t.run_id = ao_screener.run_id;
"""


def upgrade() -> None:
    op.execute(_V_RECOMMENDATION_TRACE)
    op.execute(_V_STOCK_ANALYSIS_HISTORY)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_stock_analysis_history")
    op.execute("DROP VIEW IF EXISTS v_recommendation_trace")
