"""Screener 落盘：stock_recommendations + condition_scores。"""
import json
from typing import Dict

from sqlalchemy.orm import Session

from db.models import ConditionScore, StockRecommendation
from schemas.screener import ScreenerResult


def bulk_insert(sess: Session, agent_output_id: int, result: ScreenerResult,
                code_to_sde_id: Dict[str, int]) -> Dict[str, int]:
    """写 stock_recommendations + condition_scores；返回 {code: rec_id}。"""
    code_to_rec_id: Dict[str, int] = {}
    # 按 total_score 排序赋 rank
    sorted_stocks = sorted(result.stocks, key=lambda s: s.total_score, reverse=True)
    for rank, s in enumerate(sorted_stocks, start=1):
        rec = StockRecommendation(
            agent_output_id=agent_output_id,
            stock_data_entry_id=code_to_sde_id.get(s.code),
            code=s.code,
            name=s.name,
            total_score=s.total_score,
            recommendation_level=s.recommendation_level,
            rank=rank,
            recommendation_rationale=s.recommendation_rationale,
            key_strengths_json=json.dumps(s.key_strengths, ensure_ascii=False) if s.key_strengths else None,
            key_risks_json=json.dumps(s.key_risks, ensure_ascii=False) if s.key_risks else None,
            data_gaps_json=json.dumps(s.data_gaps, ensure_ascii=False) if s.data_gaps else None,
            trigger_ref=s.trigger_ref,
        )
        sess.add(rec)
        sess.flush()
        code_to_rec_id[s.code] = rec.id
        # 级联写 condition_scores
        for cs in s.condition_scores:
            sess.add(ConditionScore(
                stock_recommendation_id=rec.id,
                condition_id=cs.condition_id,
                condition_name=cs.condition_name,
                satisfaction=cs.satisfaction,
                weight=cs.weight,
                weighted_score=cs.weighted_score,
                reasoning=cs.reasoning,
            ))
    sess.commit()
    return code_to_rec_id
