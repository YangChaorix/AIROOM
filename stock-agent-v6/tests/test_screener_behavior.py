"""Screener 行为验证：条件即数据（Phase 3 起条件源为 DB）。

S1：从 DB 软删 C3 → 重跑，输出中所有股票的 condition_scores 里不再出现 C3
S2：改 DB 中 C2 权重 → 同样输入下 total_score 变化
S3：每条 reasoning 非占位且 ≥ 15 字符
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import has_api_key, make_mock_research_report

pytestmark = pytest.mark.skipif(not has_api_key(), reason="需要 DEEPSEEK_API_KEY")


def _patched_research():
    """用 mock Research 把测试范围锁定到 Screener，避免每次测试都真跑 ReAct。"""
    def fake_run_react(state):
        trigger = state.get("trigger_summary", {})
        return make_mock_research_report(trigger.get("trigger_id", "T-MOCK"))
    return patch("agents.research._run_react", side_effect=fake_run_react)


def _run_with_db_mods(mods) -> dict:
    """mods 是一个回调函数：mods(session) 负责修改 conditions 表。"""
    from db.engine import get_session

    with get_session() as sess:
        mods(sess)
        sess.commit()

    import main
    with _patched_research():
        return main.run("default")


def test_removing_C3_removes_C3_from_screener_output():
    """S1：软删 C3 → 每只股的 condition_scores 里不应出现 C3。"""
    from db.repos.users_repo import soft_delete_condition

    def mod(sess):
        soft_delete_condition(sess, "dad_001", "C3")

    state = _run_with_db_mods(mod)
    result = state["screener_result"]
    for stock in result.stocks:
        ids = [cs.condition_id for cs in stock.condition_scores]
        assert "C3" not in ids, (
            f"C3 仍被打分（stock={stock.code}），说明条件硬编码在 Prompt/代码里。ids={ids}"
        )


def test_changing_C2_weight_changes_total_score():
    """S2：C2 权重 0.28 → 0.05，同只股总分必然变化。"""
    from db.repos.users_repo import update_condition_weight

    # 场景 A：C2=0.28（默认）
    import main
    with _patched_research():
        s1 = main.run("default")

    # 场景 B：C2=0.05
    from db.engine import get_session
    with get_session() as sess:
        update_condition_weight(sess, "dad_001", "C2", 0.05)
        sess.commit()
    with _patched_research():
        s2 = main.run("default")

    def find_score(state, code: str):
        for s in state["screener_result"].stocks:
            if s.code == code:
                return s.total_score
        return None

    a = find_score(s1, "300750")
    b = find_score(s2, "300750")
    assert a is not None and b is not None, "测试样本未出现 300750"
    assert a != b, f"修改 C2 权重 (0.28→0.05) 后 300750 总分未变 (都是 {a})，Screener 未使用权重数据"


def test_screener_reasoning_is_substantive():
    """S3：每条 reasoning ≥ 15 字符且非占位。"""
    import main
    with _patched_research():
        state = main.run("default")
    result = state["screener_result"]

    placeholders = {"满足", "不满足", "部分满足", "ok", "OK"}
    for stock in result.stocks:
        for cs in stock.condition_scores:
            assert len(cs.reasoning) >= 15, f"reasoning 过短：{cs.reasoning!r}"
            assert cs.reasoning.strip() not in placeholders, f"reasoning 是占位：{cs.reasoning!r}"
