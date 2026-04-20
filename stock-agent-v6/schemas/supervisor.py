from typing import Literal, Optional

from pydantic import BaseModel, Field


class SupervisorDecision(BaseModel):
    action: Literal[
        "dispatch_research",
        "dispatch_screener",
        "dispatch_skeptic",
        "finalize",
    ]
    instructions: str = Field(..., min_length=10)
    round: int = Field(..., ge=1, le=4)
    reasoning: str = Field(..., min_length=20)
    notes: Optional[str] = None
