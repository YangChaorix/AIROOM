from typing import Any, Dict, List, Optional, TypedDict

from .research import ResearchReport
from .screener import ScreenerResult
from .skeptic import SkepticResult
from .supervisor import SupervisorDecision


class AgentState(TypedDict, total=False):
    trigger_summary: Dict[str, Any]
    user_profile: Dict[str, Any]
    completed_steps: List[Dict[str, Any]]
    round: int
    last_decision: Optional[SupervisorDecision]
    research_report: Optional[ResearchReport]
    screener_result: Optional[ScreenerResult]
    skeptic_result: Optional[SkepticResult]
    run_started_at: str
    # ── Phase 3 DB 落盘上下文（可选，DB 未启用时不填）──
    run_id: Optional[int]
    research_agent_output_id: Optional[int]
    screener_agent_output_id: Optional[int]
    code_to_sde_id: Optional[Dict[str, int]]   # Research 落盘后传给 Screener
    code_to_rec_id: Optional[Dict[str, int]]   # Screener 落盘后传给 Skeptic
