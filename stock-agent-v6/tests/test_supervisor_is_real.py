"""Supervisor 真实性测试 —— MVP 的灵魂。

T1: 条件边 route_from_supervisor 只读 state['last_decision'].action —— 纯静态扫描，始终跑
T2: Mock LLM 替换 → 行为必须变化                  —— 需要 DEEPSEEK_API_KEY
T3: 不同 trigger → 路由序列或 instructions 不同    —— 需要 DEEPSEEK_API_KEY
T4: reasoning ≥ 20 字且非占位                     —— 需要 DEEPSEEK_API_KEY
"""
import ast
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.edges import route_from_supervisor
from tests.helpers import (
    collect_dispatch_sequence,
    collect_supervisor_decisions,
    has_api_key,
    run_graph_real,
    run_graph_with_mock_supervisor,
)


FORBIDDEN_READS = {
    "round",
    "trigger_strength",
    "completed_steps",
    "trigger_summary",
    "user_profile",
    "research_report",
    "screener_result",
    "skeptic_result",
}


# ─────────────────────────────────────────────────────────────
# T1: 静态扫描（永远跑）
# ─────────────────────────────────────────────────────────────

def test_route_function_has_no_business_logic():
    src = inspect.getsource(route_from_supervisor)
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_READS:
            raise AssertionError(
                f"route_from_supervisor 不应读取 state.{node.attr}（T1 违规）"
            )
        if isinstance(node, ast.Subscript):
            slice_node = node.slice
            if isinstance(slice_node, ast.Constant) and slice_node.value in FORBIDDEN_READS:
                raise AssertionError(
                    f"route_from_supervisor 不应读取 state['{slice_node.value}']（T1 违规）"
                )


# ─────────────────────────────────────────────────────────────
# T2-T4: 需要真 LLM（无 API key 时跳过）
# ─────────────────────────────────────────────────────────────

pytestmark_llm = pytest.mark.skipif(
    not has_api_key(),
    reason="需要 DEEPSEEK_API_KEY 或 OPENAI_API_KEY 环境变量",
)


@pytestmark_llm
def test_replacing_supervisor_llm_changes_system_behavior():
    """T2：换成固定 mock 台词本后，dispatch 序列应与真实 LLM 不同。"""
    real_state = run_graph_real("default")
    real_seq = collect_dispatch_sequence(real_state)

    # Mock: 强制连续 3 次 research，第 4 次 finalize
    mock_state = run_graph_with_mock_supervisor(
        ["dispatch_research", "dispatch_research", "dispatch_research", "finalize"],
        trigger_key="default",
    )
    mock_seq = collect_dispatch_sequence(mock_state)

    assert real_seq != mock_seq, (
        f"替换 Supervisor LLM 后系统行为未变化，说明 Supervisor 决策没有被真实使用。\n"
        f"real={real_seq}\nmock={mock_seq}"
    )


@pytestmark_llm
def test_different_triggers_produce_different_routes():
    """T3：高强度政策 vs 低强度边缘事件，路由序列或 instructions 应有差异。"""
    strong = run_graph_real("strong_policy")
    weak = run_graph_real("weak_noise")

    strong_decisions = collect_supervisor_decisions(strong)
    weak_decisions = collect_supervisor_decisions(weak)

    seq_diff = [d["action"] for d in strong_decisions] != [d["action"] for d in weak_decisions]
    reasoning_diff = any(
        a.get("reasoning") != b.get("reasoning")
        for a, b in zip(strong_decisions, weak_decisions)
    )

    assert seq_diff or reasoning_diff, (
        f"不同强度 trigger 下 Supervisor 决策完全一致，不像是在基于输入推理。\n"
        f"strong={[d['action'] for d in strong_decisions]}\n"
        f"weak={[d['action'] for d in weak_decisions]}"
    )


@pytestmark_llm
def test_supervisor_decision_contains_real_reasoning():
    """T4：reasoning 必须 ≥ 20 字符且非占位文本。"""
    state = run_graph_real("default")
    decisions = collect_supervisor_decisions(state)
    assert decisions, "未收集到任何 Supervisor 决策"

    placeholders = {"好", "ok", "OK", "继续", "进行下一步", "next"}
    for d in decisions:
        r = d.get("reasoning", "")
        assert len(r) >= 20, f"reasoning 过短，疑似伪造：{r!r}"
        assert r.strip() not in placeholders, f"reasoning 是占位文本：{r!r}"
