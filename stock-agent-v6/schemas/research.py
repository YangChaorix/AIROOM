from typing import List, Optional

from pydantic import BaseModel, Field


class StockDataEntry(BaseModel):
    code: str
    name: str
    industry: str
    leadership: Optional[str] = None
    holder_structure: Optional[str] = None
    financial_summary: Optional[str] = None
    technical_summary: Optional[str] = None
    price_benefit: Optional[str] = None
    data_gaps: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    trigger_ref: str
    candidates: List[StockDataEntry] = Field(..., min_length=1)
    overall_notes: Optional[str] = None
