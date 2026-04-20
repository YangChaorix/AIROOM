"""真实数据集成测试 —— 需要 AkShare 网络可达。

运行方式：
    pytest tests/test_real_data_integration.py -v -m real_data
默认 `pytest tests/` 不会跑这些测试（因为没有 -m real_data）。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

pytestmark = pytest.mark.real_data


def test_akshare_financial_returns_substantive_data():
    """stock_financial_data 应当返回含营收/净利等关键指标的非空 JSON。"""
    from tools.real_research_tools import stock_financial_data

    out = stock_financial_data("300750")
    data = json.loads(out)
    assert "error" not in data, f"AkShare 调用失败：{data.get('error')}"
    summary = data.get("financial_summary", "")
    assert len(summary) > 20, f"financial_summary 过短：{summary!r}"
    # 至少出现两个关键财务指标
    hits = sum(1 for kw in ("营收", "净利", "毛利", "每股", "ROE", "市盈", "资产") if kw in summary)
    assert hits >= 2, f"financial_summary 未包含足够财务指标：{summary!r}"


def test_akshare_holder_returns_structured_data():
    """stock_holder_structure 应当返回聪明钱/国资/外资分类 + 股东列表。"""
    from tools.real_research_tools import stock_holder_structure

    out = stock_holder_structure("300750")
    data = json.loads(out)
    assert "error" not in data, f"AkShare 调用失败：{data.get('error')}"
    for field in ("holder_structure", "smart_money_pct", "state_pct", "foreign_pct"):
        assert field in data, f"缺字段 {field}"
    assert "前十大股东" in data["holder_structure"] or "截至" in data["holder_structure"]


def test_akshare_technical_computes_indicators():
    """stock_technical_indicators 应当计算出 MA20 / 成交量比 / MACD 信号。"""
    from tools.real_research_tools import stock_technical_indicators

    out = stock_technical_indicators("300750")
    data = json.loads(out)
    assert "error" not in data, f"AkShare 调用失败：{data.get('error')}"
    summary = data.get("technical_summary", "")
    assert "MA20" in summary, f"缺少 MA20：{summary!r}"
    assert data.get("macd_signal") in ("golden_cross", "death_cross", "no_cross", None)


def test_akshare_industry_leaders_with_fallback():
    """新能源储能应当命中 fallback map，返回 >=2 只龙头。"""
    from tools.real_research_tools import akshare_industry_leaders

    out = akshare_industry_leaders("新能源储能")
    data = json.loads(out)
    leaders = data.get("leaders", [])
    assert len(leaders) >= 2, f"龙头数量不足：{leaders}"
    assert all("code" in l and "name" in l for l in leaders)


def test_price_trend_covers_commodity():
    """大宗商品（碳酸锂）应当有价格趋势，非大宗（如'电池包'）应 data_gap。"""
    from tools.real_research_tools import price_trend_data

    ok = json.loads(price_trend_data("碳酸锂"))
    assert ok.get("trend_summary") and "涨幅" in ok["trend_summary"], f"碳酸锂无趋势：{ok}"

    miss = json.loads(price_trend_data("某特殊型号电池包"))
    assert miss.get("data_gap"), f"非大宗应返回 data_gap：{miss}"


def test_news_search_filters_keywords():
    """search_news_from_db 应能从聚合新闻中过滤出含关键词的条目。"""
    from tools.real_research_tools import search_news_from_db

    out = json.loads(search_news_from_db("新能源 锂电", hours=48))
    assert "results" in out
    # 即使结果为 0，也应是合法结构；真实新闻流里通常能命中
    assert isinstance(out["results"], list)


def test_trigger_fetcher_returns_live_news():
    """fetch_latest_news 应返回 ≥5 条带标题的近期新闻。"""
    from tools.trigger_fetcher import fetch_latest_news

    news = fetch_latest_news(limit=20)
    assert len(news) >= 5, f"新闻数量不足：{len(news)}"
    assert all(n.get("title") for n in news), "有条目缺标题"


def test_trigger_summarize_produces_valid_structure():
    """summarize_as_trigger 应产出结构完整的 trigger dict。"""
    from tools.trigger_fetcher import fetch_latest_news, summarize_as_trigger

    news = fetch_latest_news(limit=15)
    trigger = summarize_as_trigger(news)
    for field in ("trigger_id", "headline", "industry", "type", "strength", "source", "summary"):
        assert field in trigger, f"trigger 缺字段 {field}"
    assert trigger["strength"] in ("high", "medium", "low")
    assert trigger["type"] in ("policy_landing", "industry_news", "earnings_beat", "minor_news", "price_surge")
