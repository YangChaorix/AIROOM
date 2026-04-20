"""Supervisor node —— 真 LLM 驱动（步骤 2）。

工作方式：
1. 从 config/prompts/supervisor.md 读取模板
2. 用 state 中的字段通过 str.format 注入
3. 调 LLM → 解析为 SupervisorDecision
4. 写回 state.last_decision, round, completed_steps

架构铁律：本文件内的 LLM 调用是 Supervisor 决策的**唯一来源**；路由层
（graph/edges.py）只读 last_decision.action，禁止在路由层做业务判断。
"""
import json
import re
from pathlib import Path
from typing import Any, Dict

from pydantic import ValidationError

from agents.llm_factory import build_llm
from schemas.state import AgentState
from schemas.supervisor import SupervisorDecision

_PROMPT_PATH = Path(__file__).parent.parent / "config" / "prompts" / "supervisor.md"


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _strip_code_fence(text: str) -> str:
    """剥掉 ```json ... ``` 或 ``` ... ``` 包裹。"""
    text = text.strip()
    fence_pattern = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)
    m = fence_pattern.match(text)
    if m:
        return m.group(1).strip()
    return text


def _extract_json(text: str) -> str:
    """从可能夹带解释文字的响应里抽出第一个完整 JSON 对象。"""
    cleaned = _strip_code_fence(text)
    # 若已是纯 JSON，直接返回
    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned
    # 否则寻找第一个 { ... } 块
    start = cleaned.find("{")
    if start == -1:
        return cleaned
    # 用括号匹配定位结束
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : i + 1]
    return cleaned[start:]


def _completed_steps_summary(steps) -> str:
    if not steps:
        return "（尚未执行任何子 Agent）"
    lines = []
    for i, s in enumerate(steps, 1):
        node = s.get("node", "?")
        if node == "supervisor":
            lines.append(f"{i}. [Supervisor R{s.get('round')}] 决定 {s.get('action')} — {s.get('reasoning', '')[:80]}")
        elif node == "research":
            lines.append(f"{i}. [Research] 完成，候选 {s.get('candidates_count', 0)} 只，data_gap {s.get('data_gaps_count', 0)} 项")
        elif node == "screener":
            lines.append(f"{i}. [Screener] 完成，{s.get('stocks_count', 0)} 只股票，TOP1={s.get('top_stock')}")
        elif node == "skeptic":
            lines.append(f"{i}. [Skeptic] 完成，{s.get('findings_count', 0)} 条质疑，覆盖 {s.get('covered_stocks', [])}")
        else:
            lines.append(f"{i}. [{node}]")
    return "\n".join(lines)


def _build_prompt(state: AgentState, current_round: int) -> str:
    tmpl = _load_prompt()
    profile = state.get("user_profile", {})
    conditions = profile.get("conditions", [])

    return tmpl.format(
        current_round=current_round,
        trigger_summary_json=json.dumps(state.get("trigger_summary", {}), ensure_ascii=False, indent=2),
        user_profile_conditions_json=json.dumps(conditions, ensure_ascii=False, indent=2),
        completed_steps_summary=_completed_steps_summary(state.get("completed_steps", [])),
    )


def _call_llm(prompt: str) -> str:
    llm = build_llm("supervisor")
    msg = llm.invoke(prompt)
    return msg.content if hasattr(msg, "content") else str(msg)


def _decide(state: AgentState, current_round: int) -> SupervisorDecision:
    prompt = _build_prompt(state, current_round)
    last_error: Exception = None
    for attempt in range(2):
        raw = _call_llm(prompt)
        json_text = _extract_json(raw)
        try:
            decision = SupervisorDecision.model_validate_json(json_text)
        except ValidationError as e:
            last_error = e
            prompt = prompt + f"\n\n## 上一次输出验证失败\n\n错误：{e}\n\n请严格按格式重新输出纯 JSON。"
            continue
        # 第 4 次激活强制 finalize
        if current_round >= 4 and decision.action != "finalize":
            decision = decision.model_copy(update={"action": "finalize"})
        return decision

    raise RuntimeError(f"Supervisor LLM 连续 2 次输出无效 JSON：{last_error}")


def supervisor_node(state: AgentState) -> Dict[str, Any]:
    current_round = state.get("round", 0) + 1

    if current_round >= 5:
        # 兜底：LangGraph 超出预期轮次，强制 finalize 不再调 LLM
        decision = SupervisorDecision(
            action="finalize",
            instructions="轮次上限兜底触发，直接渲染报告",
            round=4,
            reasoning="当前已超过 4 轮上限，Supervisor 不再调度子 Agent，直接 finalize 以防止死循环",
            notes=state.get("last_decision").notes if state.get("last_decision") else None,
        )
    else:
        decision = _decide(state, current_round)

    completed_steps = list(state.get("completed_steps", []))
    completed_steps.append({
        "node": "supervisor",
        "round": current_round,
        "action": decision.action,
        "reasoning": decision.reasoning,
    })

    # Phase 3：每轮 Supervisor 决策落 agent_outputs
    run_id = state.get("run_id")
    if run_id is not None:
        try:
            from db.engine import get_session
            from db.repos.agent_outputs_repo import log as log_agent_output
            with get_session() as sess:
                log_agent_output(
                    sess,
                    run_id=run_id,
                    agent_name="supervisor",
                    sequence=current_round,
                    summary=decision.reasoning,
                    payload={
                        "action": decision.action,
                        "instructions": decision.instructions,
                        "notes": decision.notes,
                    },
                )
        except Exception as e:
            # DB 失败不应中断 graph；打日志即可
            print(f"[supervisor] DB log failed: {e}", file=__import__("sys").stderr)

    return {
        "round": current_round,
        "last_decision": decision,
        "completed_steps": completed_steps,
    }
