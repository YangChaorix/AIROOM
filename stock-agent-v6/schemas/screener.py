from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ConditionScore(BaseModel):
    condition_id: str
    condition_name: str
    satisfaction: Literal[0.0, 0.5, 1.0]
    weight: float
    weighted_score: float
    reasoning: str = Field(..., min_length=15)


class StockRecommendation(BaseModel):
    code: str
    name: str
    total_score: float
    recommendation_level: Literal["recommend", "watch", "skip"]
    condition_scores: List[ConditionScore]
    data_gaps: List[str] = Field(default_factory=list)
    trigger_ref: str
    # ── Phase 3 新增业务摘要字段（LLM 一次输出，无额外调用）──
    recommendation_rationale: Optional[str] = Field(
        default=None,
        description="该股综合推荐摘要（50-150 字），含与同批的简短对比",
    )
    key_strengths: List[str] = Field(default_factory=list, description="核心优势 2-5 条")
    key_risks: List[str] = Field(default_factory=list, description="核心风险 1-4 条")


class ScreenerResult(BaseModel):
    stocks: List[StockRecommendation] = Field(..., min_length=1)
    threshold_used: float
    # ── Phase 3 新增横向对比摘要 ──
    comparison_summary: Optional[str] = Field(
        default=None,
        description="本批候选横向对比总结（100-300 字）；单股场景可为空或简短说明",
    )
