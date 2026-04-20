"""实时触发源：AkShare 最新要闻 → LLM 摘要成结构化 trigger。

用法：
    >>> news = fetch_latest_news(limit=30)
    >>> trigger = summarize_as_trigger(news)

trigger 结构严格对齐 data/triggers_fixtures.json 的字段（trigger_id/headline/industry/
type/strength/source/published_at/summary）。
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import akshare as ak

from agents.llm_factory import build_llm
from tools._cache import ttl_cache

_SUMMARY_PROMPT_PATH = Path(__file__).parent.parent / "config" / "prompts" / "trigger_summarize.md"


@ttl_cache(seconds=300)
def _fetch_cjzc(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        df = ak.stock_info_cjzc_em()
        return [
            {"title": r.get("标题", ""), "content": str(r.get("摘要", ""))[:400],
             "source": "东财-财经早餐", "published_at": str(r.get("发布时间", ""))}
            for _, r in df.head(limit).iterrows()
        ]
    except Exception:
        return []


@ttl_cache(seconds=300)
def _fetch_global(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        df = ak.stock_info_global_em()
        return [
            {"title": r.get("标题", ""), "content": str(r.get("摘要", ""))[:400],
             "source": "东财-全球资讯", "published_at": str(r.get("发布时间", ""))}
            for _, r in df.head(limit).iterrows()
        ]
    except Exception:
        return []


@ttl_cache(seconds=600)
def _fetch_cctv(limit: int = 10) -> List[Dict[str, Any]]:
    try:
        df = ak.news_cctv()
        return [
            {"title": r.get("title", ""), "content": str(r.get("content", ""))[:400],
             "source": "央视网", "published_at": str(r.get("date", ""))}
            for _, r in df.head(limit).iterrows()
        ]
    except Exception:
        return []


def fetch_latest_news(limit: int = 30) -> List[Dict[str, Any]]:
    """聚合 3 个 AkShare 新闻源，返回标题+摘要+来源+时间的结构化列表。"""
    items: List[Dict[str, Any]] = []
    items.extend(_fetch_cjzc(limit=max(limit // 2, 10)))
    items.extend(_fetch_global(limit=max(limit // 2, 10)))
    items.extend(_fetch_cctv(limit=10))
    # 按时间倒序
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return items[:limit]


_DEFAULT_SUMMARY_PROMPT = """\
你是一个 A 股专业分析师。下面是最近的市场要闻列表。请从中**挑选一条最具投资主题/行情催化意义**的新闻，
忽略政治时政/国际外交/地方民生等与 A 股选股无关的内容，把它压缩为下列 JSON（严格格式，不要 markdown 代码块、不要额外文字）：

{{
  "trigger_id": "T-{date}-LIVE",
  "headline": "新闻标题（简短）",
  "industry": "受影响的 A 股行业（如'新能源储能'、'半导体'、'医药'）",
  "type": "policy_landing | industry_news | earnings_beat | minor_news | price_surge 之一",
  "strength": "high | medium | low（基于对行业资金面/估值的冲击）",
  "source": "新闻来源",
  "published_at": "新闻原始时间",
  "summary": "对 A 股投资者的含义说明 + 关键词（50-150 字）"
}}

## 新闻列表

{news_json}

重要提醒：
- 如果所有新闻都与 A 股主题关联弱，选最接近的一条，strength 设为 "low"
- trigger_id 的 {date} 替换为今天日期，格式 YYYYMMDD
"""


def _load_summary_prompt() -> str:
    if _SUMMARY_PROMPT_PATH.exists():
        return _SUMMARY_PROMPT_PATH.read_text(encoding="utf-8")
    return _DEFAULT_SUMMARY_PROMPT


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, re.DOTALL)
    return m.group(1).strip() if m else text


def _extract_json_obj(text: str) -> str:
    cleaned = _strip_fence(text)
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


def summarize_as_trigger(news_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """让 chat 模型从新闻列表里挑一条摘要成结构化 trigger。"""
    if not news_items:
        return _fallback_trigger("无最新新闻可用")

    date_str = datetime.now().strftime("%Y%m%d")
    # 只给 LLM 前 15 条，避免 context 过长
    top = news_items[:15]
    prompt = _load_summary_prompt().format(
        date=date_str,
        news_json=json.dumps(top, ensure_ascii=False, indent=2),
    )

    llm = build_llm("research")  # 用 chat 模型（非 reasoner），摘要任务足够
    try:
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        trigger = json.loads(_extract_json_obj(text))
    except Exception as e:
        return _fallback_trigger(f"LLM 摘要失败: {e}")

    # 补全必要字段
    trigger.setdefault("trigger_id", f"T-{date_str}-LIVE")
    trigger.setdefault("published_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return trigger


def _fallback_trigger(reason: str) -> Dict[str, Any]:
    now = datetime.now()
    return {
        "trigger_id": f"T-{now.strftime('%Y%m%d')}-FALLBACK",
        "headline": "[fallback] 无可用实时触发新闻",
        "industry": "通用",
        "type": "minor_news",
        "strength": "low",
        "source": "fallback",
        "published_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": f"触发源获取失败：{reason}；管道继续但 Research 缺乏明确方向。",
    }


def get_live_trigger(limit: int = 30) -> Dict[str, Any]:
    """一站式：拉新闻 + 摘要为 trigger（Phase 3：新闻同时入 news_items 表）。"""
    news = fetch_latest_news(limit=limit)

    # Phase 3：新闻入库 + 把 id 回填到 trigger.source_news_ids（失败不阻塞）
    source_news_ids: List[int] = []
    try:
        from db.engine import get_session
        from db.repos.news_items_repo import bulk_upsert
        with get_session() as sess:
            result = bulk_upsert(sess, news)
            source_news_ids = result["ids"]
    except Exception as e:
        import sys
        print(f"[trigger_fetcher] news_items upsert 失败: {e}", file=sys.stderr)

    trigger = summarize_as_trigger(news)
    if source_news_ids:
        trigger["source_news_ids"] = source_news_ids[:15]  # 只保留前 15 条
    return trigger
