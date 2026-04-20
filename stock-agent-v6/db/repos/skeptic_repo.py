"""Skeptic 落盘：skeptic_findings（含强 FK 到 stock_recommendations）。"""
from typing import Dict

from sqlalchemy.orm import Session

from db.models import SkepticFinding
from schemas.skeptic import SkepticResult


def bulk_insert(sess: Session, agent_output_id: int, result: SkepticResult,
                code_to_rec_id: Dict[str, int]) -> int:
    """写 skeptic_findings；按 stock_code 查 recommendation FK。返回插入条数。"""
    count = 0
    for f in result.findings:
        row = SkepticFinding(
            agent_output_id=agent_output_id,
            stock_recommendation_id=code_to_rec_id.get(f.stock_code),
            stock_code=f.stock_code,
            finding_type=f.finding_type,
            content=f.content,
        )
        sess.add(row)
        count += 1
    sess.commit()
    return count
