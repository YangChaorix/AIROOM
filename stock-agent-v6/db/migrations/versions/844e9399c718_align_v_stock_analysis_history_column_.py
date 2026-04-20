"""align v_stock_analysis_history column level alias

Revision ID: 844e9399c718
Revises: 95ebdbf32364
Create Date: 2026-04-19 11:06:14.353360

统一两个视图的列命名：v_recommendation_trace 用 `level` 别名，v_stock_analysis_history
原列名 `recommendation_level` —— 此迁移 DROP + 重建 view，新增 `AS level` 别名。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "844e9399c718"
down_revision: Union[str, Sequence[str], None] = "95ebdbf32364"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_VIEW = """
CREATE VIEW v_stock_analysis_history AS
SELECT
  r.code, r.name,
  r.total_score,
  r.recommendation_level AS level,
  r.rank,
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
  r.created_at AS rec_created_at
FROM stock_recommendations r
JOIN agent_outputs ao_screener
  ON ao_screener.id = r.agent_output_id AND ao_screener.agent_name = 'screener'
JOIN triggers t ON t.run_id = ao_screener.run_id;
"""

_OLD_VIEW = """
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
    op.execute("DROP VIEW IF EXISTS v_stock_analysis_history")
    op.execute(_NEW_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_stock_analysis_history")
    op.execute(_OLD_VIEW)
