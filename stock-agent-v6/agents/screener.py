"""Screener Agent —— 单次 LLM 调用（步骤 4）。

核心铁律：条件和权重只从 DB `conditions` 表注入 Prompt，绝不硬编码。
改 DB（或通过 API 改）即改选股逻辑，不改代码（S1/S2 测试守护）。

Phase 3 前读 config/user_profile.json；Phase 3 后读 state.user_profile（由 main.py 从 DB 填充）。
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from pydantic import ValidationError

from agents.llm_factory import build_llm
from schemas.screener import ScreenerResult
from schemas.state import AgentState

_PROMPT_PATH = Path(__file__).parent.parent / "config" / "prompts" / "screener.md"


def _scoreable_conditions(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "description": c["description"],
            "weight": c["weight"],
        }
        for c in profile.get("conditions", [])
        if c.get("layer") in ("screener", "entry")
    ]


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


def _load_profile_from_state_or_db(state: AgentState) -> Dict[str, Any]:
    """优先用 state.user_profile（main.py 已从 DB 填充）；
    若 state 里没有（边缘场景），直接从 DB 重新读一次；都没有再 fallback JSON。
    """
    p = state.get("user_profile")
    if p and p.get("conditions"):
        return p
    # 尝试 DB
    try:
        from db.engine import get_session
        from db.repos.users_repo import load_profile as db_load
        with get_session() as sess:
            return db_load(sess, state.get("user_profile", {}).get("user_id", "dad_001"))
    except Exception:
        pass
    # 最后 fallback：JSON（仅用于测试裸跑场景）
    json_path = Path(__file__).parent.parent / "config" / "user_profile.json"
    return json.loads(json_path.read_text(encoding="utf-8"))


def _build_prompt(state: AgentState) -> str:
    profile = _load_profile_from_state_or_db(state)
    threshold = profile.get("advanced_settings", {}).get("recommendation_threshold", 0.65)
    scoreable = _scoreable_conditions(profile)

    report = state["research_report"]
    research_json = report.model_dump_json(indent=2)

    tmpl = _PROMPT_PATH.read_text(encoding="utf-8")
    return tmpl.format(
        recommendation_threshold=threshold,
        scoreable_conditions_json=json.dumps(scoreable, ensure_ascii=False, indent=2),
        research_report_json=research_json,
    )


def _call_llm(prompt: str) -> str:
    llm = build_llm("screener")
    msg = llm.invoke(prompt)
    return msg.content if hasattr(msg, "content") else str(msg)


def _recompute_totals(result: ScreenerResult) -> None:
    """用 condition_scores 的 weighted_score 加和覆盖 LLM 给的 total_score，
    并按 threshold_used 重算 recommendation_level。LLM 不做算术，保证前端
    展示的加权和 == 总分，且评级与总分一致（S3 守护）。
    """
    threshold = result.threshold_used
    for s in result.stocks:
        # 每条 weighted_score 也强制 = satisfaction × weight（LLM 偶尔也在这里乱写）
        recomputed = 0.0
        for cs in s.condition_scores:
            cs.weighted_score = round(cs.satisfaction * cs.weight, 4)
            recomputed += cs.weighted_score
        s.total_score = round(recomputed, 4)
        if s.total_score >= threshold:
            s.recommendation_level = "recommend"
        elif s.total_score >= 0.5:
            s.recommendation_level = "watch"
        else:
            s.recommendation_level = "skip"


def _score(state: AgentState) -> ScreenerResult:
    prompt = _build_prompt(state)
    last_error: Exception = None
    for attempt in range(2):
        raw = _call_llm(prompt)
        json_text = _extract_json_object(raw)
        try:
            data = json.loads(json_text)
            result = ScreenerResult(**data)
            _recompute_totals(result)
            return result
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            prompt = prompt + f"\n\n## 上一次输出验证失败\n错误：{e}\n请严格按 ScreenerResult JSON 重新输出。"
    raise RuntimeError(f"Screener LLM 连续 2 次输出无效 JSON/Schema：{last_error}")


def screener_node(state: AgentState) -> Dict[str, Any]:
    result = _score(state)
    # 按总分降序
    result.stocks.sort(key=lambda s: s.total_score, reverse=True)

    completed_steps = list(state.get("completed_steps", []))
    completed_steps.append({
        "node": "screener",
        "stocks_count": len(result.stocks),
        "top_stock": result.stocks[0].code if result.stocks else None,
    })

    update: Dict[str, Any] = {
        "screener_result": result,
        "completed_steps": completed_steps,
    }

    # Phase 3：落 agent_outputs + stock_recommendations + condition_scores
    run_id = state.get("run_id")
    if run_id is not None:
        try:
            from db.engine import get_session
            from db.repos.agent_outputs_repo import log as log_agent_output
            from db.repos.screener_repo import bulk_insert
            with get_session() as sess:
                ao_id = log_agent_output(
                    sess,
                    run_id=run_id,
                    agent_name="screener",
                    sequence=1,
                    summary=result.comparison_summary,  # ★ 横向对比存入 summary
                    payload={
                        "threshold_used": result.threshold_used,
                        "candidates_count": len(result.stocks),
                    },
                )
                code_to_rec_id = bulk_insert(
                    sess, ao_id, result,
                    code_to_sde_id=state.get("code_to_sde_id") or {},
                )
            update["screener_agent_output_id"] = ao_id
            update["code_to_rec_id"] = code_to_rec_id
        except Exception as e:
            print(f"[screener] DB log failed: {e}", file=__import__("sys").stderr)

    return update
