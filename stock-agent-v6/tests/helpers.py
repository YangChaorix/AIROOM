"""Test helpers for swapping real LLM calls with deterministic mocks."""
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# 内联 mock 数据（Phase 2 后 stocks_mock.json 已删除，测试不再依赖 tools/）
_MOCK_STOCKS: List[Dict[str, Any]] = [
    {
        "code": "300750",
        "name": "宁德时代",
        "industry": "动力电池",
        "leadership": "[MOCK] 全球动力电池市占率 37%",
        "holder_structure": "[MOCK] 前十大股东私募约 18%，个人投资者 42%，合计聪明钱 60%",
        "financial_summary": "[MOCK] 2025 营收 4200 亿 (+28%)，净利 490 亿 (+35%)，PE 28x",
        "technical_summary": "[MOCK] MA20 向上，成交量放大，MACD 金叉",
        "price_benefit": "[MOCK] 碳酸锂价格上涨 18%，公司下游转嫁能力强",
        "data_gaps": [],
    },
    {
        "code": "002594",
        "name": "比亚迪",
        "industry": "新能源车",
        "leadership": "[MOCK] 国内新能源车销量第一",
        "holder_structure": "[MOCK] 以外资+国资为主，私募占比仅 8%",
        "financial_summary": "[MOCK] 2025 营收 6800 亿 (+22%)，净利 380 亿 (+18%)",
        "technical_summary": "[MOCK] 价格横盘，未见量能突破",
        "price_benefit": "[MOCK] 整车价格承压",
        "data_gaps": ["Q4 分红政策"],
    },
    {
        "code": "002460",
        "name": "赣锋锂业",
        "industry": "锂矿",
        "leadership": "[MOCK] 国内锂盐产能前三",
        "holder_structure": "[MOCK] 知名私募 3 家合计 12%，个人 35%",
        "financial_summary": "[MOCK] 2025 营收 520 亿 (+15%)",
        "technical_summary": "[MOCK] 成交量突破 1.8 倍",
        "price_benefit": "[MOCK] 碳酸锂涨价直接受益",
        "data_gaps": [],
    },
]


def has_api_key() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY")) or bool(os.getenv("OPENAI_API_KEY"))


# ─────────────────────────────────────────────────────────────
# Supervisor mock
# ─────────────────────────────────────────────────────────────

def make_supervisor_mock_caller(actions: List[str], reasonings: Optional[List[str]] = None) -> Callable[[str], str]:
    _counter = {"i": 0}

    def _fake_call(prompt: str) -> str:
        idx = min(_counter["i"], len(actions) - 1)
        _counter["i"] += 1
        action = actions[idx]
        reasoning = (reasonings[idx] if reasonings and idx < len(reasonings)
                     else f"[MOCK] 顺序台词本第 {idx + 1} 条，强制返回 {action}，用于验证 Supervisor 是否真在决策")
        payload = {
            "action": action,
            "instructions": f"[MOCK] 指令：请执行 {action} 对应的任务（测试占位 ≥10 字）",
            "round": min(idx + 1, 3),
            "reasoning": reasoning,
            "notes": "[MOCK] 测试用台词",
        }
        return json.dumps(payload, ensure_ascii=False)

    return _fake_call


# ─────────────────────────────────────────────────────────────
# Research mock
# ─────────────────────────────────────────────────────────────

def make_mock_research_report(trigger_ref: str = "T-MOCK"):
    from schemas.research import ResearchReport, StockDataEntry

    candidates = [
        StockDataEntry(**c, sources=["[MOCK] inline test fixture"])
        for c in _MOCK_STOCKS
    ]
    return ResearchReport(
        trigger_ref=trigger_ref,
        candidates=candidates,
        overall_notes="[MOCK] 测试用 Research 报告（内联 fixture，不依赖网络/AkShare）",
    )


# ─────────────────────────────────────────────────────────────
# 组合：所有 agent 都 mock 的端到端运行
# ─────────────────────────────────────────────────────────────

@contextlib.contextmanager
def all_agents_mocked(supervisor_actions: List[str]):
    """上下文管理器：同时 mock 所有会真调 LLM 的 agent。"""
    fake_supervisor = make_supervisor_mock_caller(supervisor_actions)

    def fake_research_run_react(state):
        trigger = state.get("trigger_summary", {})
        return make_mock_research_report(trigger.get("trigger_id", "T-MOCK"))

    patches = [
        patch("agents.supervisor._call_llm", side_effect=fake_supervisor),
        patch("agents.research._run_react", side_effect=fake_research_run_react),
    ]

    # 若 screener/skeptic 的真实现存在（步骤 4/5 完成后），也一并 mock
    try:
        import agents.screener as _screener_mod  # noqa
        if hasattr(_screener_mod, "_call_llm"):
            from tests.helpers_screener_skeptic import fake_screener_call_llm  # lazy
            patches.append(patch("agents.screener._call_llm", side_effect=fake_screener_call_llm))
    except Exception:
        pass
    try:
        import agents.skeptic as _skeptic_mod  # noqa
        if hasattr(_skeptic_mod, "_call_llm"):
            from tests.helpers_screener_skeptic import fake_skeptic_call_llm  # lazy
            patches.append(patch("agents.skeptic._call_llm", side_effect=fake_skeptic_call_llm))
    except Exception:
        pass

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


def run_graph_all_mocked(supervisor_actions: List[str], trigger_key: str = "default"):
    import main
    with all_agents_mocked(supervisor_actions):
        return main.run(trigger_key)


def run_graph_with_mock_supervisor(actions: List[str], trigger_key: str = "default"):
    """仅 mock Supervisor（保留测试语义，等价于 all_agents_mocked 但只换 supervisor）。"""
    return run_graph_all_mocked(actions, trigger_key)


def run_graph_real(trigger_key: str = "default"):
    import main
    return main.run(trigger_key)


def collect_dispatch_sequence(state) -> List[str]:
    return [s["action"] for s in state.get("completed_steps", []) if s.get("node") == "supervisor"]


def collect_supervisor_decisions(state) -> List[dict]:
    return [s for s in state.get("completed_steps", []) if s.get("node") == "supervisor"]
