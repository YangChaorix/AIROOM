from typing import List, Literal

from pydantic import BaseModel, Field


class SkepticFinding(BaseModel):
    stock_code: str
    finding_type: Literal["logic_risk", "data_gap"]
    content: str = Field(..., min_length=20)


class SkepticResult(BaseModel):
    findings: List[SkepticFinding] = Field(..., min_length=2)
    covered_stocks: List[str]
