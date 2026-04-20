"""金丝雀 —— 管道结构跑通（不依赖 API key）+ 真 LLM 端到端（依赖 API key）。

每完成一步，这两个测试都必须仍然通过，否则说明管道塌了。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import has_api_key, run_graph_real, run_graph_with_mock_supervisor


def test_pipeline_structure_with_mock_supervisor():
    """无 API key 场景：用固定台词本验证 4 站管道结构完好 + DB 落盘成功。"""
    state = run_graph_with_mock_supervisor(
        ["dispatch_research", "dispatch_screener", "dispatch_skeptic", "finalize"],
        trigger_key="default",
    )

    finalize_steps = [s for s in state.get("completed_steps", []) if s.get("node") == "finalize"]
    assert finalize_steps, "管道结构失败：未到达 finalize"

    supervisor_steps = [s for s in state.get("completed_steps", []) if s.get("node") == "supervisor"]
    assert len(supervisor_steps) >= 3, f"Supervisor 至少应激活 3 次，实际 {len(supervisor_steps)}"

    # Phase 3：验证 DB 落盘而非 Markdown 文件
    run_id = state.get("run_id")
    assert run_id is not None, "run_id 未注入 state，DB 落盘不生效"

    from sqlalchemy import select
    from db.engine import get_session
    from db.models import AgentOutput, Run, StockRecommendation

    with get_session() as sess:
        run = sess.scalar(select(Run).where(Run.id == run_id))
        assert run is not None and run.status == "completed"

        agent_outputs = sess.scalars(
            select(AgentOutput).where(AgentOutput.run_id == run_id)
        ).all()
        agent_names = {ao.agent_name for ao in agent_outputs}
        assert {"supervisor", "research", "screener", "skeptic"}.issubset(agent_names)

        recs = sess.scalars(
            select(StockRecommendation).join(AgentOutput).where(AgentOutput.run_id == run_id)
        ).all()
        assert len(recs) >= 1, "没有股票推荐入库"


@pytest.mark.skipif(not has_api_key(), reason="需要 DEEPSEEK_API_KEY")
def test_pipeline_end_to_end_with_real_llm():
    """有 API key 场景：真 LLM 跑完整流程，DB 落盘有 Screener 推荐 + Skeptic 质疑。"""
    state = run_graph_real("default")

    finalize_steps = [s for s in state.get("completed_steps", []) if s.get("node") == "finalize"]
    assert finalize_steps, "真 LLM 端到端失败：未到达 finalize"

    run_id = state.get("run_id")
    assert run_id is not None

    from sqlalchemy import select
    from db.engine import get_session
    from db.models import SkepticFinding, StockRecommendation, AgentOutput

    with get_session() as sess:
        recs = sess.scalars(
            select(StockRecommendation).join(AgentOutput).where(AgentOutput.run_id == run_id)
        ).all()
        assert recs, "Screener 未落推荐股"
        findings = sess.scalars(
            select(SkepticFinding).join(AgentOutput).where(AgentOutput.run_id == run_id)
        ).all()
        assert findings, "Skeptic 未落质疑"
