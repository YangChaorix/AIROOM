"""Research Agent 真 ReAct 验证。

R1: 单次执行工具调用 ≥ 2 次（需 API key）
R3: 从 research_tools.json 删掉工具 → data_gaps 出现对应项（需 API key）

R2（mock LLM 只调 1 次工具对比）因为涉及替换 LLM 底层行为、对 LangChain 内部耦合较深，
在 MVP 阶段简化为"静态约束"：research.md 明确要求 ≥2 次工具调用，已由 R1 端到端验证。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import has_api_key

pytestmark = pytest.mark.skipif(not has_api_key(), reason="需要 DEEPSEEK_API_KEY")

_TOOLS_JSON = Path(__file__).parent.parent / "config" / "tools" / "research_tools.json"


def _find_research_step(state):
    for s in state.get("completed_steps", []):
        if s.get("node") == "research":
            return s
    return None


def test_research_makes_multiple_tool_calls():
    """R1：真实跑一次，research 节点记录的 tool_call_count ≥ 2。"""
    import main
    state = main.run("default")
    r = _find_research_step(state)
    assert r is not None, "未找到 research 节点执行记录"
    count = r.get("tool_call_count", 0)
    assert count >= 2, (
        f"Research 只调用了 {count} 次工具，不像真 ReAct。"
        f"tool_names={r.get('tool_names')}"
    )


def test_removing_tool_from_json_produces_data_gap():
    """R3：移除 stock_technical_indicators → 至少一只股票的 technical_summary 为 None
    或 data_gaps 含技术面项。"""
    backup = _TOOLS_JSON.read_text(encoding="utf-8")
    try:
        specs = json.loads(backup)
        reduced = [s for s in specs if s["name"] != "stock_technical_indicators"]
        _TOOLS_JSON.write_text(json.dumps(reduced, ensure_ascii=False, indent=2), encoding="utf-8")

        import main
        state = main.run("default")
        report = state["research_report"]

        tech_keywords = ("技术", "technical", "量能", "MACD", "均线", "成交量")
        missing_tech = any(
            c.technical_summary is None
            or any(kw in (g or "") for kw in tech_keywords for g in c.data_gaps)
            for c in report.candidates
        )
        assert missing_tech, (
            "删除 stock_technical_indicators 后 Research 仍给出全部技术面信息，"
            "工具清单外置未生效或 LLM 在幻觉。"
        )

        # 也检查 research 节点记录的 tool_names 里不再有该工具
        r = _find_research_step(state)
        assert r and "stock_technical_indicators" not in r.get("tool_names", []), (
            "JSON 已移除该工具，但执行记录中仍出现该工具调用"
        )
    finally:
        _TOOLS_JSON.write_text(backup, encoding="utf-8")
