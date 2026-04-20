"""Phase 4 单股分析模式测试。

- 代码/名称 resolve
- single_stock_trigger 合成（focus_codes 结构正确）
- 端到端：python main.py --stock 300750 产出报告含 3 只股
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import has_api_key


# ── 不依赖网络/LLM 的结构测试 ──

def test_build_trigger_structure():
    """本测试先于真实 AkShare 调用，验证合成 trigger 结构（用 mock resolve）。"""
    from unittest.mock import patch
    with patch("tools.stock_resolver.resolve", return_value={
        "code": "300750", "name": "宁德时代", "industry": "动力电池",
    }), patch("tools.stock_resolver.fetch_peers", return_value=[
        {"code": "002594", "name": "比亚迪", "note": ""},
        {"code": "300274", "name": "阳光电源", "note": ""},
    ]):
        from tools.single_stock_trigger import build_single_stock_trigger
        t = build_single_stock_trigger("300750", with_peers=True)

    assert t["type"] == "individual_stock_analysis"
    assert t["source"] == "user_request"
    assert t["focus_codes"] == ["300750", "002594", "300274"]
    assert t["focus_primary"] == "300750"
    assert t["peer_names"] == ["比亚迪", "阳光电源"]
    assert "宁德时代" in t["headline"]


def test_build_trigger_no_peers():
    """with_peers=False 只包主股 focus_codes."""
    from unittest.mock import patch
    with patch("tools.stock_resolver.resolve", return_value={
        "code": "300750", "name": "宁德时代", "industry": "动力电池",
    }):
        from tools.single_stock_trigger import build_single_stock_trigger
        t = build_single_stock_trigger("300750", with_peers=False)

    assert t["focus_codes"] == ["300750"]
    assert t["focus_primary"] == "300750"
    assert t["peer_names"] == []


# ── 需要网络（AkShare）的真数据测试 ──

@pytest.mark.real_data
def test_resolve_by_code():
    from tools.stock_resolver import resolve
    r = resolve("300750")
    assert r["code"] == "300750"
    assert "宁德" in r["name"] or r["name"] == "宁德时代"


@pytest.mark.real_data
def test_resolve_by_name():
    from tools.stock_resolver import resolve
    r = resolve("宁德时代")
    assert r["code"] == "300750"


@pytest.mark.real_data
def test_resolve_invalid_raises():
    from tools.stock_resolver import resolve
    with pytest.raises(ValueError):
        resolve("999999")


@pytest.mark.real_data
def test_industry_map_fallback_works():
    """300750 在 industry_leaders_map.json 的动力电池行业里。"""
    from tools.stock_resolver import resolve
    r = resolve("300750")
    # 至少不是"未分类"
    assert r["industry"] != "未分类", f"industry 反查失败：{r}"


@pytest.mark.real_data
@pytest.mark.skipif(not has_api_key(), reason="需要 DEEPSEEK_API_KEY")
def test_single_stock_mode_end_to_end():
    """端到端：main.run(stock='300750') 跑通完整流程，DB 落 individual_stock_analysis 类型 trigger + 多只推荐股。"""
    import main
    state = main.run(stock="300750", with_peers=True)

    assert state.get("run_id") is not None
    run_id = state["run_id"]

    from sqlalchemy import select
    from db.engine import get_session
    from db.models import StockRecommendation, Trigger, AgentOutput

    with get_session() as sess:
        trigger = sess.scalar(select(Trigger).where(Trigger.run_id == run_id))
        assert trigger is not None
        assert trigger.type == "individual_stock_analysis"
        assert trigger.mode == "individual_stock"

        import json as _json
        meta = _json.loads(trigger.metadata_json or "{}")
        assert meta.get("focus_primary") == "300750"
        assert "300750" in (meta.get("focus_codes") or [])

        recs = sess.scalars(
            select(StockRecommendation).join(AgentOutput).where(AgentOutput.run_id == run_id)
        ).all()
        assert len(recs) >= 1
        # 主股应出现
        assert any(r.code == "300750" for r in recs)
