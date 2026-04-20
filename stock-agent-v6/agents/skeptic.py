"""Skeptic Agent —— 单次 LLM 调用（步骤 5）。

对 Screener TOP5 做一次对抗推理，找 logic_risk + data_gap。
"""
import json
import re
from pathlib import Path
from typing import Any, Dict

from pydantic import ValidationError

from agents.llm_factory import build_llm
from schemas.skeptic import SkepticResult
from schemas.state import AgentState

_PROMPT_PATH = Path(__file__).parent.parent / "config" / "prompts" / "skeptic.md"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, re.DOTALL)
    return m.group(1).strip() if m else text


def _extract_json_object(text: str) -> str:
    cleaned = _strip_code_fence(text)
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    start = cleaned.find("{")
    if start == -1:
        return cleaned
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1]
    return cleaned[start:]


def _build_prompt(state: AgentState) -> str:
    screener = state["screener_result"]
    report = state["research_report"]

    top5 = screener.stocks[:5]
    top_payload = [s.model_dump() for s in top5]

    tmpl = _PROMPT_PATH.read_text(encoding="utf-8")
    return tmpl.format(
        top_candidates_json=json.dumps(top_payload, ensure_ascii=False, indent=2),
        research_report_json=report.model_dump_json(indent=2),
    )


def _call_llm(prompt: str) -> str:
    llm = build_llm("skeptic")
    msg = llm.invoke(prompt)
    return msg.content if hasattr(msg, "content") else str(msg)


def _critique(state: AgentState) -> SkepticResult:
    prompt = _build_prompt(state)
    last_error: Exception = None
    for attempt in range(2):
        raw = _call_llm(prompt)
        json_text = _extract_json_object(raw)
        try:
            data = json.loads(json_text)
            return SkepticResult(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            prompt = prompt + f"\n\n## 上一次输出验证失败\n错误：{e}\n请严格按 SkepticResult JSON 重新输出。"
    raise RuntimeError(f"Skeptic LLM 连续 2 次输出无效 JSON/Schema：{last_error}")


def skeptic_node(state: AgentState) -> Dict[str, Any]:
    result = _critique(state)

    completed_steps = list(state.get("completed_steps", []))
    completed_steps.append({
        "node": "skeptic",
        "findings_count": len(result.findings),
        "covered_stocks": result.covered_stocks,
    })

    update: Dict[str, Any] = {
        "skeptic_result": result,
        "completed_steps": completed_steps,
    }

    # Phase 3：落 agent_outputs + skeptic_findings
    run_id = state.get("run_id")
    if run_id is not None:
        try:
            from db.engine import get_session
            from db.repos.agent_outputs_repo import log as log_agent_output
            from db.repos.skeptic_repo import bulk_insert
            logic_count = sum(1 for f in result.findings if f.finding_type == "logic_risk")
            gap_count = sum(1 for f in result.findings if f.finding_type == "data_gap")
            with get_session() as sess:
                ao_id = log_agent_output(
                    sess,
                    run_id=run_id,
                    agent_name="skeptic",
                    sequence=1,
                    summary=f"本次覆盖 {len(result.covered_stocks)} 只股票，产出 {logic_count} 条 logic_risk + {gap_count} 条 data_gap",
                    payload={
                        "covered_stocks": result.covered_stocks,
                        "logic_risk_count": logic_count,
                        "data_gap_count": gap_count,
                    },
                )
                bulk_insert(sess, ao_id, result, code_to_rec_id=state.get("code_to_rec_id") or {})
        except Exception as e:
            print(f"[skeptic] DB log failed: {e}", file=__import__("sys").stderr)

    return update
