"""
个股多维度分析 Agent
输入：股票代码列表（如 ["000001", "600036"]）
输出：每只股票的多维原始数据 + D1-D6 六维评分 + LLM 综合分析报告（Markdown）
"""

import json
import logging
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import build_llm as _settings_build_llm
from tools.stock_data import get_stock_basic_info, get_financial_indicators, get_stock_news_em
from tools.shareholder_tools import get_top_shareholders
from tools.technical_tools import calc_volume_breakthrough, calc_long_term_trend

logger = logging.getLogger(__name__)

ANALYST_SYSTEM_PROMPT = """你是专业A股分析师，根据提供的多维度数据对指定股票进行独立综合分析，输出六维评分和 Markdown 报告。

**六维评分标准（每项 0-3 分，满分 18 分）**

【D1 行业龙头地位】（0-3 分）
- 3分：主营产品市场份额全国或全球前3，且主营产品占公司总营收70%以上
- 2分：行业前5，主营产品占营收50%-70%
- 1分：行业前10，或主营产品占比较低
- 0分：非行业核心企业

【D2 近期业务催化】（0-3 分）——基于近期新闻与财务趋势综合判断
- 3分：近期有明确正面催化（大额合同、政策直接利好、业绩超预期等），且催化与主营强相关
- 2分：有一定催化信号，但确定性或主营关联度一般
- 1分：催化信号较弱或仅为边缘利好
- 0分：无明显催化，或有负面事件/业绩压力

【D3 股东结构稳定性】（0-3 分）——参考已提供的 D3得分 字段
- 3分：前10大流通股东以私募基金+个人大股东为主，连续未减仓甚至加仓，合计占流通股60%以上
- 2分：满足持仓稳定条件，但占比在40%-60%之间
- 1分：机构持仓为主但持仓稳定
- 0分：股东结构不符合或无法查证

【D4 中长期上涨趋势】（0-3 分）——参考均线趋势数据
- 3分：MA60/MA120/MA250 多头排列，股价位于三线之上，趋势明确向上
- 2分：均线初步多头排列或处于关键位置，有趋势成立迹象
- 1分：短期有所反弹但中期均线仍压制，趋势不明朗
- 0分：均线空头排列，股价持续走弱

【D5 技术突破信号】（0-3 分）——参考已提供的 D5得分 字段
- 3分：近3日日均交易量较过去20日环比增长5倍以上，日换手率明显放大，股价突破近期高点
- 2分：成交量放大2-5倍，但突破信号不明显
- 1分：成交量小幅放大，无明显突破
- 0分：缩量或无明显变化

【D6 估值合理性】（0-3 分）——参考财务指标与近期涨幅
- 3分：股价长期横盘或近期才开始启动，ROE稳定，PE/PB处于历史低位或行业低位
- 2分：估值适中，尚有上升空间
- 1分：估值偏高，但基本面支撑
- 0分：明显高估或基本面恶化

**输出格式（严格 JSON，不要输出其他内容）**
```json
{
  "scores": {
    "D1_龙头地位": {"score": 0, "reason": "15字以内"},
    "D2_近期催化": {"score": 0, "reason": "15字以内"},
    "D3_股东结构": {"score": 0, "reason": "15字以内"},
    "D4_上涨趋势": {"score": 0, "reason": "15字以内"},
    "D5_技术突破": {"score": 0, "reason": "15字以内"},
    "D6_估值合理": {"score": 0, "reason": "15字以内"}
  },
  "total_score": 0,
  "recommendation": "综合推荐理由（60字以内）",
  "risk": "主要风险点（40字以内）",
  "report": "## Markdown 格式详细分析报告（含各维度分析、催化剂、风险点、操作建议）"
}
```"""


def _build_llm():
    return _settings_build_llm("screener")


def _collect_stock_data(code: str) -> dict:
    """采集单只股票的 6 个维度原始数据，任一维度异常不中断"""
    data = {}

    logger.debug(f"[{code}] ── D1/基本信息 ──")
    try:
        data["basic"] = get_stock_basic_info(code)
        logger.debug(f"[{code}] 基本信息: {json.dumps(data['basic'], ensure_ascii=False, default=str)}")
    except Exception as e:
        data["basic_error"] = str(e)
        logger.warning(f"[{code}] 基本信息采集失败: {e}")

    logger.debug(f"[{code}] ── D4/技术趋势（均线）──")
    try:
        data["technical"] = calc_long_term_trend(code)
        t = data["technical"]
        logger.info(f"[{code}] D4技术: MA60={t.get('MA60')} MA120={t.get('MA120')} MA250={t.get('MA250')} 趋势={t.get('趋势描述')}")
        logger.debug(f"[{code}] D4详情: {json.dumps(t, ensure_ascii=False, default=str)}")
    except Exception as e:
        data["technical_error"] = str(e)
        logger.warning(f"[{code}] 技术趋势采集失败: {e}")

    logger.debug(f"[{code}] ── D5/量价突破 ──")
    try:
        data["volume"] = calc_volume_breakthrough(code)
        v = data["volume"]
        logger.info(f"[{code}] D5量价: 量比={v.get('量比(3日/20日)')} 得分={v.get('d5_score')} {v.get('d5_desc','')}")
        logger.debug(f"[{code}] D5详情: {json.dumps(v, ensure_ascii=False, default=str)}")
    except Exception as e:
        data["volume_error"] = str(e)
        logger.warning(f"[{code}] 量价突破采集失败: {e}")

    logger.debug(f"[{code}] ── D3/股东结构 ──")
    try:
        data["shareholders"] = get_top_shareholders(code)
        sh = data["shareholders"]
        d3 = (sh.get("筹码结构分析") or {}).get("D3得分", "N/A")
        logger.info(f"[{code}] D3股东: 得分={d3}")
        logger.debug(f"[{code}] D3详情: {json.dumps(sh, ensure_ascii=False, default=str)}")
    except Exception as e:
        data["shareholders_error"] = str(e)
        logger.warning(f"[{code}] 股东结构采集失败: {e}")

    logger.debug(f"[{code}] ── D6/财务指标 ──")
    try:
        data["financial"] = get_financial_indicators(code)
        fi = data["financial"]
        logger.info(f"[{code}] D6财务: {json.dumps(fi, ensure_ascii=False, default=str)[:120]}...")
        logger.debug(f"[{code}] D6详情: {json.dumps(fi, ensure_ascii=False, default=str)}")
    except Exception as e:
        data["financial_error"] = str(e)
        logger.warning(f"[{code}] 财务指标采集失败: {e}")

    # 新闻：本地 DB 检索，不足时回退到东方财富个股新闻接口
    try:
        from tools.db import db as _db
        from datetime import datetime, timedelta
        import hashlib as _hashlib

        # 读取系统配置
        _src_raw = _db.get_config('analyst_news_sources', '') or ''
        _hours   = int(_db.get_config('analyst_news_lookback_hours', 72) or 72)
        _filter_sources = [s.strip() for s in _src_raw.split(',') if s.strip()]
        since_dt = (datetime.now() - timedelta(hours=_hours)).strftime("%Y-%m-%d %H:%M:%S")

        basic_info = data.get("basic") or {}
        stock_name = basic_info.get("股票名称") or basic_info.get("股票简称") or ""
        keywords = [kw for kw in [stock_name, code] if kw]

        # 第一步：本地 DB 搜索
        local_news = _db.search_news(
            keywords, limit=15,
            sources=_filter_sources or None,
            since_dt=since_dt,
        )
        logger.info(f"[{code}] 本地新闻 {len(local_news)} 条（回溯{_hours}h，渠道={'全部' if not _filter_sources else _filter_sources}）")

        # 第二步：本地不足 3 条时，调用东方财富个股新闻接口补充
        em_news = []
        if len(local_news) < 3:
            logger.info(f"[{code}] 本地新闻不足，调用 stock_news_em 补充...")
            em_raw = get_stock_news_em(code, limit=15, since_dt=since_dt)
            today = datetime.now().strftime("%Y-%m-%d")
            saved = 0
            for item in em_raw:
                # 生成 hash，写入 DB 供后续复用
                news_hash = _hashlib.md5(item["title"][:60].strip().lower().encode()).hexdigest()[:16]
                item_with_hash = {"id": news_hash, **item}
                try:
                    _db.add_news_items([item_with_hash], today)
                    saved += 1
                except Exception:
                    pass
                em_news.append(item)
            logger.info(f"[{code}] stock_news_em 补充 {len(em_news)} 条（新写入 DB {saved} 条）")

        # 合并去重（优先本地，EM 补充不重复的）
        seen_titles = {n.get("title", "") for n in local_news}
        merged = list(local_news)
        for item in em_news:
            t = item.get("title", "")
            if t and t not in seen_titles:
                seen_titles.add(t)
                merged.append({
                    "title":    item.get("title", ""),
                    "source":   item.get("source", ""),
                    "pub_time": item.get("pub_time", ""),
                    "content":  (item.get("content") or "")[:200],
                })

        data["news"] = [
            {
                "title":    n.get("title", ""),
                "source":   n.get("source", ""),
                "pub_time": n.get("pub_time", ""),
                "content":  (n.get("content") or "")[:200],
            }
            for n in merged
        ]
        data["news_config"] = {
            "lookback_hours": _hours,
            "sources": _filter_sources or "全部渠道",
            "local_count": len(local_news),
            "em_count": len(em_news),
        }
        logger.info(f"[{code}] 合并后共 {len(data['news'])} 条新闻（本地 {len(local_news)} + EM {len(em_news)}）")
    except Exception as e:
        data["news_error"] = str(e)
        logger.warning(f"[{code}] 新闻采集失败: {e}")

    return data


def _parse_llm_output(content: str) -> dict:
    """解析 LLM 输出的 JSON，容错处理 markdown 代码块包裹"""
    text = content.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM 输出 JSON 解析失败，降级返回 report 原文")
        return {"scores": {}, "total_score": None, "recommendation": "", "risk": "", "report": content}


def _call_llm(code: str, raw_data: dict) -> dict:
    """调用 LLM，返回含 scores + report 的 dict"""
    llm = _build_llm()

    basic = raw_data.get("basic", {})
    name = basic.get("股票名称") or basic.get("股票简称") or basic.get("name") or code

    news = raw_data.get("news") or []
    news_cfg = raw_data.get("news_config", {})
    hours = news_cfg.get("lookback_hours", 72)
    local_cnt = news_cfg.get("local_count", len(news))
    em_cnt    = news_cfg.get("em_count", 0)
    news_src_label = f"本地缓存{local_cnt}条" + (f" + 东方财富EM {em_cnt}条" if em_cnt else "")
    if news:
        news_text = "\n".join(
            f"- [{n.get('pub_time', '')}/{n.get('source', '')}] {n.get('title', '')}：{n.get('content', '')}"
            for n in news
        )
    else:
        news_text = raw_data.get("news_error") or f"近{hours}小时无相关新闻"

    # D3/D5 量化得分直接传给 LLM 作参考
    d3_score = ((raw_data.get("shareholders") or {}).get("筹码结构分析") or {}).get("D3得分", "N/A")
    d5_score = (raw_data.get("volume") or {}).get("d5_score", "N/A")

    human_content = f"""请对以下股票进行六维评分和综合分析，严格按照 JSON 格式输出，不要输出其他内容。

股票：{name}（{code}）

【基本信息】
{json.dumps(raw_data.get("basic", raw_data.get("basic_error", "获取失败")), ensure_ascii=False, indent=2, default=str)}

【技术走势（均线趋势）】
{json.dumps(raw_data.get("technical", raw_data.get("technical_error", "获取失败")), ensure_ascii=False, indent=2, default=str)}

【量价信号（D5量化得分={d5_score}）】
{json.dumps(raw_data.get("volume", raw_data.get("volume_error", "获取失败")), ensure_ascii=False, indent=2, default=str)}

【筹码结构（D3量化得分={d3_score}）】
{json.dumps(raw_data.get("shareholders", raw_data.get("shareholders_error", "获取失败")), ensure_ascii=False, indent=2, default=str)}

【财务指标（近4期）】
{json.dumps(raw_data.get("financial", raw_data.get("financial_error", "获取失败")), ensure_ascii=False, indent=2, default=str)}

【近{hours}小时相关新闻（共{len(news)}条，来源：{news_src_label}）】
{news_text}

注意：
- D3得分、D5得分已由量化程序计算，可直接参考
- 只输出 JSON，不要输出其他文字
- 各维度 reason 控制在15字以内，report 用 Markdown 格式详细展开"""

    logger.debug(f"[{code}] LLM 输入（human_content 前500字）:\n{human_content[:500]}...")
    messages = [
        SystemMessage(content=ANALYST_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]
    resp = llm.invoke(messages)
    logger.debug(f"[{code}] LLM 原始输出:\n{resp.content}")
    return _parse_llm_output(resp.content)


def run_stock_analyst(codes: list) -> dict:
    """
    入参：股票代码列表，如 ["000001", "600036"]
    返回：{
      "results": [
        {
          "code": "000001",
          "name": "平安银行",
          "raw_data": {...},
          "scores": {"D1_龙头地位": {"score": 2, "reason": "..."}, ...},
          "total_score": 12,
          "recommendation": "...",
          "risk": "...",
          "report": "## Markdown...",
          "error": None
        }
      ],
      "model": "deepseek-chat",
      "analyzed_at": "2026-03-20 16:40:00"
    }
    """
    logger.info(f"=== 个股分析 Agent 启动，分析股票：{codes} ===")

    try:
        from config.settings import get_llm_config
        cfg = get_llm_config("screener")
        model_name = cfg.model_name
    except Exception:
        model_name = None

    results = []
    for code in codes:
        logger.info(f"[{code}] 开始数据采集...")
        raw_data = _collect_stock_data(code)

        basic = raw_data.get("basic", {})
        name = basic.get("股票名称") or basic.get("股票简称") or basic.get("name") or code

        logger.info(f"[{code}] 调用 LLM 进行评分与分析...")
        error = None
        llm_result = {}
        try:
            llm_result = _call_llm(code, raw_data)
        except Exception as e:
            error = str(e)
            logger.error(f"[{code}] LLM 调用失败: {e}")

        scores = llm_result.get("scores", {})
        total_score = llm_result.get("total_score")
        if total_score is None and scores:
            total_score = sum(v.get("score", 0) for v in scores.values() if isinstance(v, dict))

        score_summary = " | ".join(
            f"{k.split('_')[0]}={v.get('score','?')}({v.get('reason','')})"
            for k, v in scores.items() if isinstance(v, dict)
        )
        logger.info(f"[{code}] ✅ 分析完成 总分={total_score}  {score_summary}")
        logger.info(f"[{code}] 推荐：{llm_result.get('recommendation', '')} | 风险：{llm_result.get('risk', '')}")
        logger.debug(f"[{code}] 完整报告:\n{llm_result.get('report', '')}")

        results.append({
            "code": code,
            "name": name,
            "raw_data": raw_data,
            "scores": scores,
            "total_score": total_score,
            "recommendation": llm_result.get("recommendation", ""),
            "risk": llm_result.get("risk", ""),
            "report": llm_result.get("report", ""),
            "error": error,
        })

    analyzed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(
        f"=== 个股分析完成 {analyzed_at} | 共{len(results)}只 | "
        + " ".join(f"{r['code']}({r['name']})={r['total_score']}分" for r in results)
        + " ==="
    )
    return {
        "results": results,
        "model": model_name,
        "analyzed_at": analyzed_at,
    }
