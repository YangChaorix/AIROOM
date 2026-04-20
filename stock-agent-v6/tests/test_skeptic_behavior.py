"""Skeptic 行为验证。

K1：findings 覆盖 logic_risk + data_gap 两种类型
K2：不同 Screener 输入产生不同 Skeptic 输出
K3：每条 finding ≥ 20 字符且非占位文本
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import has_api_key, make_mock_research_report

pytestmark = pytest.mark.skipif(not has_api_key(), reason="需要 DEEPSEEK_API_KEY")


def _patched_research():
    def fake_run_react(state):
        trigger = state.get("trigger_summary", {})
        return make_mock_research_report(trigger.get("trigger_id", "T-MOCK"))
    return patch("agents.research._run_react", side_effect=fake_run_react)


def test_skeptic_has_both_finding_types():
    """K1：findings 至少各包含 1 条 logic_risk + 1 条 data_gap。"""
    import main
    with _patched_research():
        state = main.run("default")
    result = state["skeptic_result"]
    types = {f.finding_type for f in result.findings}
    assert {"logic_risk", "data_gap"}.issubset(types), (
        f"Skeptic 只输出了 {types}，缺少对抗类型覆盖"
    )


def test_skeptic_output_varies_with_input():
    """K2：不同 trigger 触发的不同 Screener 结果 → Skeptic 输出应有差异。"""
    import main
    with _patched_research():
        s1 = main.run("strong_policy")
        s2 = main.run("weak_noise")
    f1 = [f.content for f in s1["skeptic_result"].findings]
    f2 = [f.content for f in s2["skeptic_result"].findings]
    assert f1 != f2, "不同输入下 Skeptic 产出完全相同，疑似写死"


def test_skeptic_findings_are_substantive():
    """K3：每条 content ≥ 20 字符，且非单纯占位文本。"""
    import main
    with _patched_research():
        state = main.run("default")
    result = state["skeptic_result"]

    trivial_phrases = {"市场存在不确定性", "需谨慎", "未知"}
    for f in result.findings:
        assert len(f.content) >= 20, f"finding 过短：{f.content!r}"
        # 若是泛泛话术，必须至少 30 字有展开
        if any(p in f.content for p in trivial_phrases):
            assert len(f.content) > 30, f"泛泛话术无具体展开：{f.content!r}"
