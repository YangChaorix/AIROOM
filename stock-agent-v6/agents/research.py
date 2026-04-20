"""Research Agent —— 真 ReAct（Phase 2 起用真实数据）。

- 从 config/tools/research_tools.json 读取启用的工具名单
- 映射到 tools/real_research_tools.py 的同名函数（AkShare 真实接口）
- 用 LangChain AgentExecutor 跑 ReAct 循环（max_iterations=12 兜底）
- 最终响应解析为 ResearchReport Pydantic
- 候选股起点提示从 data/industry_leaders_map.json 取（按 trigger.industry 查映射）
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from agents.llm_factory import build_llm
from schemas.research import ResearchReport, StockDataEntry
from schemas.state import AgentState
from tools.real_research_tools import TOOL_FUNCTIONS

_PROMPT_PATH = Path(__file__).parent.parent / "config" / "prompts" / "research.md"
_TOOLS_JSON_PATH = Path(__file__).parent.parent / "config" / "tools" / "research_tools.json"
_INDUSTRY_MAP_PATH = Path(__file__).parent.parent / "data" / "industry_leaders_map.json"


def _load_enabled_tools() -> List[StructuredTool]:
    specs = json.loads(_TOOLS_JSON_PATH.read_text(encoding="utf-8"))
    tools: List[StructuredTool] = []
    for spec in specs:
        name = spec["name"]
        if name not in TOOL_FUNCTIONS:
            continue  # JSON 引用了未实现的工具，跳过
        func = TOOL_FUNCTIONS[name]
        tools.append(StructuredTool.from_function(
            func=func,
            name=name,
            description=spec["description"],
        ))
    return tools


def _candidate_hint(trigger: Dict[str, Any], limit: int = 3) -> str:
    """给 Research LLM 的候选股起点提示。

    - 事件驱动（focus_codes 为空）：从 industry_leaders_map.json 按行业取龙头
    - 个股分析（focus_codes 非空，Phase 4）：直接用 focus_codes，不扩大范围
    """
    focus = trigger.get("focus_codes") or []
    if focus:
        # Phase 4 单股模式：锁定 focus_codes
        brief = [{"code": c, "name": "", "note": "focus_codes 指定（主股 + 对标）"}
                 for c in focus[:limit] or focus]  # 不截断 focus_codes 自身长度
        return json.dumps(brief, ensure_ascii=False, indent=2)

    # 事件驱动模式：按 industry 查映射表
    industry = trigger.get("industry", "")
    try:
        table = json.loads(_INDUSTRY_MAP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "[]"
    entries: List[Dict[str, Any]] = []
    for key, val in table.items():
        if key.startswith("_"):
            continue
        if key == industry or industry in key or key in industry:
            entries = val
            break
    brief = [{"code": e["code"], "name": e["name"], "note": e.get("note", "")}
             for e in entries[:limit]]
    return json.dumps(brief, ensure_ascii=False, indent=2)


def _build_prompt_messages(system_text: str) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", system_text),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])


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
                return cleaned[start:i + 1]
    return cleaned[start:]


def _parse_report(output_text: str, trigger_ref: str) -> ResearchReport:
    json_text = _extract_json_object(output_text)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Research 输出不是合法 JSON: {e}\n原文: {output_text[:500]}")
    # 确保 trigger_ref 存在
    data.setdefault("trigger_ref", trigger_ref)
    try:
        return ResearchReport(**data)
    except ValidationError as e:
        raise RuntimeError(f"Research 输出不符合 ResearchReport schema: {e}")


def _fallback_report_from_steps(intermediate, trigger_ref: str) -> ResearchReport:
    """当 ReAct 没能输出最终 JSON（如撞到 max_iterations）时，
    根据工具调用历史拼出一份残缺的 ResearchReport 作为兜底，保证管道不崩。"""
    codes_seen: Dict[str, Dict[str, Any]] = {}
    tools_used: List[str] = []

    for step in intermediate:
        action = step[0]
        observation = step[1]
        tool_name = getattr(action, "tool", None)
        if tool_name:
            tools_used.append(tool_name)
        try:
            obs_data = json.loads(observation) if isinstance(observation, str) else {}
        except Exception:
            obs_data = {}

        code = obs_data.get("code")
        if code:
            entry = codes_seen.setdefault(code, {"code": code, "name": obs_data.get("name", ""),
                                                  "industry": "", "sources": []})
            entry["sources"].append(tool_name or "?")
            if "financial_summary" in obs_data:
                entry["financial_summary"] = obs_data["financial_summary"]
            if "holder_structure" in obs_data:
                entry["holder_structure"] = obs_data["holder_structure"]
            if "technical_summary" in obs_data:
                entry["technical_summary"] = obs_data["technical_summary"]

    # 至少保证 1 只候选股
    if not codes_seen:
        # ReAct 连候选都没拿到——用 industry_leaders_map.json 的第一个作兜底
        try:
            table = json.loads(_INDUSTRY_MAP_PATH.read_text(encoding="utf-8"))
            first_industry = next(k for k in table if not k.startswith("_"))
            first_entry = table[first_industry][0]
            codes_seen[first_entry["code"]] = {
                "code": first_entry["code"],
                "name": first_entry["name"],
                "industry": first_industry,
                "sources": ["[fallback] industry_leaders_map.json"],
                "data_gaps": ["ReAct 未完成，所有字段通过 fallback 填充"],
            }
        except Exception:
            codes_seen["000000"] = {
                "code": "000000",
                "name": "占位",
                "industry": "未知",
                "sources": ["[fallback] empty"],
                "data_gaps": ["ReAct 完全未产出结果"],
            }

    candidates = []
    for v in codes_seen.values():
        v.setdefault("data_gaps", ["ReAct 未输出最终 JSON，该股部分字段可能缺失"])
        candidates.append(StockDataEntry(**v))

    return ResearchReport(
        trigger_ref=trigger_ref,
        candidates=candidates,
        overall_notes="[fallback] ReAct 因 max_iterations 中止；从 intermediate_steps 重建报告",
    )


def _run_react(state: AgentState):
    """执行 ReAct 循环，返回 (ResearchReport, intermediate_steps)。"""
    system_text = _PROMPT_PATH.read_text(encoding="utf-8")
    tools = _load_enabled_tools()
    llm = build_llm("research")

    prompt = _build_prompt_messages(system_text)
    agent = create_openai_tools_agent(llm, tools, prompt)
    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        max_iterations=12,
        early_stopping_method="force",
        return_intermediate_steps=True,
        handle_parsing_errors=True,
        verbose=False,
    )

    trigger = state.get("trigger_summary", {})
    trigger_ref = trigger.get("trigger_id", "UNKNOWN")
    instructions = ""
    if state.get("last_decision"):
        instructions = state["last_decision"].instructions

    user_input = (
        f"### Supervisor 下达的研究指令\n{instructions}\n\n"
        f"### 触发信号\n```json\n{json.dumps(trigger, ensure_ascii=False, indent=2)}\n```\n\n"
        f"### 候选股票池提示\n```json\n{_candidate_hint(trigger, limit=3)}\n```\n\n"
        f"**执行约束**：\n"
        f"- 至少调用工具 2 次、至多调用 6 次\n"
        f"- 调用工具次数达到 4 次后应当考虑停止\n"
        f"- 停止后**立刻**输出 ResearchReport JSON（纯 JSON，无其他文字）\n"
        f"- 不要循环重复调用同一个工具同一个参数\n"
    )

    result = executor.invoke({"input": user_input})
    output = result.get("output", "")
    intermediate = result.get("intermediate_steps", [])
    # 若 agent 因 max_iterations 未输出有效 JSON，用 intermediate_steps 拼兜底 report
    try:
        report = _parse_report(output, trigger_ref)
    except RuntimeError:
        report = _fallback_report_from_steps(intermediate, trigger_ref)
    return report, intermediate


def research_node(state: AgentState) -> Dict[str, Any]:
    res = _run_react(state)
    # 支持 _run_react 被 patch 成只返回 ResearchReport 的情况（测试）
    if isinstance(res, tuple):
        report, intermediate = res
    else:
        report, intermediate = res, []

    tool_call_count = len(intermediate)
    tool_names = [step[0].tool for step in intermediate if hasattr(step[0], "tool")]

    completed_steps = list(state.get("completed_steps", []))
    completed_steps.append({
        "node": "research",
        "candidates_count": len(report.candidates),
        "data_gaps_count": sum(len(c.data_gaps) for c in report.candidates),
        "tool_call_count": tool_call_count,
        "tool_names": tool_names,
    })

    update: Dict[str, Any] = {
        "research_report": report,
        "completed_steps": completed_steps,
    }

    # Phase 3：落 agent_outputs + stock_data_entries + tool_calls
    run_id = state.get("run_id")
    if run_id is not None:
        try:
            from db.engine import get_session
            from db.repos.agent_outputs_repo import log as log_agent_output
            from db.repos.research_repo import (
                bulk_insert_stock_data_entries,
                bulk_insert_tool_calls,
            )
            with get_session() as sess:
                ao_id = log_agent_output(
                    sess,
                    run_id=run_id,
                    agent_name="research",
                    sequence=1,
                    summary=report.overall_notes,
                    payload={
                        "tool_call_count": tool_call_count,
                        "tool_names": tool_names,
                        "candidates_count": len(report.candidates),
                        "data_gaps_count": sum(len(c.data_gaps) for c in report.candidates),
                    },
                )
                code_to_sde_id = bulk_insert_stock_data_entries(sess, ao_id, report)
                bulk_insert_tool_calls(sess, ao_id, intermediate)
            update["research_agent_output_id"] = ao_id
            update["code_to_sde_id"] = code_to_sde_id
        except Exception as e:
            print(f"[research] DB log failed: {e}", file=__import__("sys").stderr)

    return update
