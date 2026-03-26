"""
Agent 1：信息触发 Agent（v1.2 升级）
每日 09:15 运行，扫描三类触发条件（C1/C4/C6）
v1.1 新增：
  - 事件新鲜度评估（freshness）
  - Serper Web 搜索政策新闻
  - 触发后调用 event_tracker.mark_event_seen()
v1.2 新增：
  - 新闻分批压缩：超过阈值时先按批摘要再合并分析，避免 context 截断
输出：命中信息 + 受影响行业/企业列表（JSON）
"""

import json
import logging
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import settings, build_llm as _build_llm
from tools.news_tools import get_all_trigger_news
from tools.news_collector import NewsCacheManager, collect_all_due_sources
from tools.price_monitor import scan_all_industry_prices, COMMODITY_FUTURES_MAP, get_commodity_price_change
from tools.search_tools import search_multiple_queries
from tools import event_tracker

logger = logging.getLogger(__name__)

# ── 新闻分批压缩配置 ─────────────────────────────────────
_NEWS_COMPRESS_THRESHOLD = 150   # 超过此条数启动一级压缩
_NEWS_BATCH_SIZE = 100           # 一级压缩每批新闻数量
_SUMMARY_COMPRESS_THRESHOLD = 60 # 一级摘要超过此条数启动二级压缩
_SUMMARY_BATCH_SIZE = 20         # 二级压缩每批摘要数量

# 一级压缩提示词：原始新闻 → 关键事件
_SUMMARIZE_PROMPT = """你是新闻摘要助手。请从以下新闻中提取5-10条对A股市场可能有影响的关键事件。

要求：
- 只保留有实质内容的事件（政策、价格变动、重大事件、监管动作）
- 合并同一事件的多条重复报道，只保留信息最完整的一条
- 每条保留：标题、来源、时间、核心内容（1-2句话，不超过80字）
- 无实质内容的资讯（人事变动、业绩预告、一般公告）直接丢弃
- 只输出JSON数组，不要其他文字

输出格式：
[
  {"标题": "...", "来源": "...", "时间": "...", "内容": "..."},
  ...
]"""

# 二级压缩提示词：一级摘要 → 核心事件
_SUMMARIZE_L2_PROMPT = """你是新闻摘要助手。以下是已经初步筛选过的关键事件摘要，请进一步合并去重，提炼出最核心的5条事件。

要求：
- 跨批次同一事件合并为一条，保留最完整的信息
- 优先保留政策类、涨价类、重大转折类事件
- 每条核心内容不超过100字
- 只输出JSON数组，不要其他文字

输出格式：
[
  {"标题": "...", "来源": "...", "时间": "...", "内容": "..."},
  ...
]"""


def _flatten_news(news_data: dict) -> list[dict]:
    """把按来源分组的 news_data 展开为扁平列表"""
    skip_keys = {"采集统计"}
    items = []
    for key, val in news_data.items():
        if key in skip_keys or not isinstance(val, list):
            continue
        for item in val:
            items.append({
                "标题": item.get("标题", ""),
                "内容": item.get("内容", ""),
                "时间": item.get("时间", ""),
                "来源": key,
            })
    return items


def _call_compress_llm(system_prompt: str, batch: list[dict],
                       batch_label: str, llm, fallback_limit: int = 10) -> list[dict]:
    """通用压缩调用，失败时降级保留前 fallback_limit 条标题"""
    batch_text = json.dumps(batch, ensure_ascii=False, indent=2)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"{batch_label}（{len(batch)}条）：\n\n{batch_text}"),
    ]
    try:
        resp = llm.invoke(messages)
        content = resp.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        result = json.loads(content)
        if isinstance(result, list):
            return result
    except Exception as e:
        logger.warning(f"  {batch_label} 压缩失败({e})，降级保留前{fallback_limit}条")
    return [
        {"标题": item.get("标题", ""), "来源": item.get("来源", ""),
         "时间": item.get("时间", ""), "内容": ""}
        for item in batch[:fallback_limit]
    ]


def _compress_news_if_needed(news_data: dict, llm) -> tuple[str, bool]:
    """
    两级压缩：
      一级：原始新闻 > 150条 → 每批100条压缩为5-10条关键事件
      二级：一级摘要 > 60条  → 每批20条再压缩为5条核心事件
    不超阈值时直接返回原始文本。
    返回 (news_text_for_llm, was_compressed)
    """
    all_items = _flatten_news(news_data)
    total = len(all_items)

    if total <= _NEWS_COMPRESS_THRESHOLD:
        logger.info(f"新闻总数 {total} 条，未超过阈值({_NEWS_COMPRESS_THRESHOLD})，直接分析")
        return json.dumps(news_data, ensure_ascii=False, indent=2), False

    # ── 一级压缩 ──────────────────────────────────────────
    l1_batches = (total + _NEWS_BATCH_SIZE - 1) // _NEWS_BATCH_SIZE
    logger.info(
        f"[一级压缩] 新闻 {total} 条，分 {l1_batches} 批（每批{_NEWS_BATCH_SIZE}条）压缩..."
    )
    l1_summaries = []
    for i in range(0, total, _NEWS_BATCH_SIZE):
        batch = all_items[i:i + _NEWS_BATCH_SIZE]
        batch_idx = i // _NEWS_BATCH_SIZE + 1
        label = f"一级第{batch_idx}/{l1_batches}批新闻"
        result = _call_compress_llm(_SUMMARIZE_PROMPT, batch, label, llm)
        logger.info(f"  {label}：{len(batch)}条 → {len(result)}条关键事件")
        l1_summaries.extend(result)

    logger.info(f"[一级压缩完成] {total}条原始新闻 → {len(l1_summaries)}条关键事件")

    # ── 二级压缩（一级摘要仍过多时） ─────────────────────
    if len(l1_summaries) <= _SUMMARY_COMPRESS_THRESHOLD:
        logger.info(f"一级摘要 {len(l1_summaries)} 条，未超过二级阈值({_SUMMARY_COMPRESS_THRESHOLD})，无需二级压缩")
        final_summaries = l1_summaries
        compress_note = f"原始{total}条 →（一级压缩）→ {len(final_summaries)}条关键事件"
    else:
        l2_batches = (len(l1_summaries) + _SUMMARY_BATCH_SIZE - 1) // _SUMMARY_BATCH_SIZE
        logger.info(
            f"[二级压缩] 一级摘要 {len(l1_summaries)} 条，超过阈值({_SUMMARY_COMPRESS_THRESHOLD})，"
            f"分 {l2_batches} 批再压缩..."
        )
        l2_summaries = []
        for i in range(0, len(l1_summaries), _SUMMARY_BATCH_SIZE):
            batch = l1_summaries[i:i + _SUMMARY_BATCH_SIZE]
            batch_idx = i // _SUMMARY_BATCH_SIZE + 1
            label = f"二级第{batch_idx}/{l2_batches}批摘要"
            result = _call_compress_llm(_SUMMARIZE_L2_PROMPT, batch, label, llm, fallback_limit=5)
            logger.info(f"  {label}：{len(batch)}条 → {len(result)}条核心事件")
            l2_summaries.extend(result)

        logger.info(
            f"[二级压缩完成] {len(l1_summaries)}条一级摘要 → {len(l2_summaries)}条核心事件"
        )
        final_summaries = l2_summaries
        compress_note = (
            f"原始{total}条 →（一级压缩）→ {len(l1_summaries)}条"
            f" →（二级压缩）→ {len(final_summaries)}条核心事件"
        )

    stats = dict(news_data.get("采集统计", {}))
    stats["压缩说明"] = compress_note
    compressed = {
        "采集统计": stats,
        "关键事件摘要（已压缩）": final_summaries,
    }
    return json.dumps(compressed, ensure_ascii=False, indent=2), True


TRIGGER_SYSTEM_PROMPT = """你是一个专注A股市场的信息扫描分析师。你的任务是每天早晨扫描当日最新信息，识别可能对特定行业或企业产生实质性影响的事件，为后续选股分析提供初步范围。

**工作原则**
你只关注三类信息（OR关系，符合任意一类即触发）：

【类型1：实质性产业政策】
- 来源：国家权威部门（发改委、工信部、商务部、国资委、国家能源局等官方渠道），非个人发布
- 时间：今日发布或正式实施
- 标准：必须是针对具体行业的实质性措施，有具体数字、指标、限制或补贴的政策才算。领导人泛泛表态"支持发展某行业"不算。
- 判断示例：
  ✅"国家限制稀土出口，设置开采总量上限"——有实质限制措施
  ✅"美国FDA要求所有食品饮料添加牛磺酸"——有具体强制要求
  ❌"政府表示将大力支持新能源汽车发展"——无具体措施

【类型2：产品涨价信号】
- 标准：某行业主营产品价格近3个月同比或环比涨幅超过20%，且涨价原因为供需不平衡（需求增加或供给减少）
- 需说明：是什么产品、哪个区域市场、涨价幅度、涨价原因
- 注意：价格上涨必须有基本面支撑，不要把短期投机波动当成涨价信号

【类型3：重大转折事件】
- 定义：可能从根本上改变某行业供需关系的突发性事件
- 包括：国际局势变化（战争、制裁、封锁）、重大监管行动（行业整治、企业关停）、技术突破或重大事故
- 判断标准：这个事件是否会改变供给端或需求端的结构？改变是否有持续性？
- 示例：某国开始全面整治稀土乱采（改变供给结构）；霍尔木兹海峡封锁（改变石油供应）

**【重要】事件新鲜度判断**
对每条触发信息，须额外评估：这个信息对市场而言是否是新增信息？
- 如果是持续超过14天的已知背景事件（如长期地缘冲突），需标注"⚠️ 低新鲜度：市场可能已price in"
- 如果事件有新的实质性升级（如冲突升级至新级别、新的关键节点），则视为新信息
- 低新鲜度事件仍然输出，但影响强度评估需相应下调

**输出格式**
对每条触发信息，输出：
1. 信息摘要（2-3句，注明来源和发布时间）
2. 触发类型（政策/涨价/转折事件）
3. 直接受益行业（最核心受益的行业，1-3个）
4. 可能受益企业范围（包括上游原材料、核心制造、下游应用，各列2-3家）
5. 影响强度评估（强/中/弱）+ 判断理由
6. 注意事项（例如：政策力度待观察；涨价可能是短期现象等）
7. 新鲜度评估（高/低）+ 判断理由

**特别注意**
- 宁可漏掉，不要误报。模糊的、没有实质内容的信息不要输出
- 同一事件可能触发多个行业，请分别列出
- 上下游关联很重要：一个行业的利好，往往对其上游原材料企业影响更大

**最终请以JSON格式输出**，结构如下：
{
  "date": "YYYY-MM-DD",
  "has_triggers": true/false,
  "triggers": [
    {
      "summary": "信息摘要",
      "type": "政策|涨价|转折事件",
      "industries": ["行业1", "行业2"],
      "companies": {
        "上游": ["企业A", "企业B"],
        "核心": ["企业C", "企业D"],
        "下游": ["企业E"]
      },
      "strength": "强|中|弱",
      "reason": "判断理由",
      "caution": "注意事项",
      "freshness": "高|低",
      "freshness_reason": "判断理由"
    }
  ],
  "summary": "今日触发情况简述"
}"""


def build_llm():
    return _build_llm("trigger")


def run_trigger_agent() -> dict:
    """
    运行触发Agent：
    1. 采集新闻数据（含财联社电报）
    2. Serper Web 搜索政策新闻（v1.1 新增）
    3. 检测期货涨价（C4）
    4. 调用LLM分析触发条件（含新鲜度评估）
    5. 标记触发事件为已见（v1.1 新增）
    6. 返回触发结果
    """
    logger.info("=== 触发Agent 启动 (v1.1) ===")
    today = datetime.now().strftime("%Y-%m-%d")

    # Step 1: 读取新闻缓存，不足时实时采集
    logger.info("读取当日新闻缓存...")

    # 读取初筛新闻配置
    from tools.db import db as _db
    _sources_raw = _db.get_config('screener_news_sources', '') or ''
    _lookback_hours = int(_db.get_config('screener_news_lookback_hours', 0) or 0)
    _filter_sources = [s.strip() for s in _sources_raw.split(',') if s.strip()]
    logger.info(
        f"初筛新闻配置：渠道={'全部' if not _filter_sources else str(_filter_sources)}，"
        f"回溯={'当天0点起' if _lookback_hours == 0 else f'过去{_lookback_hours}小时'}"
    )

    try:
        mgr = NewsCacheManager()
        cache = mgr.load_today()
        total_cached = len(cache.get("news", []))

        if total_cached >= 10:
            logger.info(f"使用当日新闻缓存：{total_cached} 条")
            news_data = mgr.get_news_for_analysis(
                sources=_filter_sources or None, lookback_hours=_lookback_hours
            )
            stats = news_data.get("采集统计", {})
            logger.info(
                f"缓存统计：总计 {stats.get('总条数', 0)} 条，"
                f"时间跨度 {stats.get('时间跨度', 'N/A')}，"
                f"最近1小时新增 {stats.get('最近1小时新增', 0)} 条"
            )
        else:
            logger.info(f"缓存不足（{total_cached}条），执行实时采集...")
            collect_all_due_sources(mgr)
            news_data = mgr.get_news_for_analysis(
                sources=_filter_sources or None, lookback_hours=_lookback_hours
            )
            stats = news_data.get("采集统计", {})
            logger.info(
                f"实时采集完成：总计 {stats.get('总条数', 0)} 条，"
                f"时间跨度 {stats.get('时间跨度', 'N/A')}"
            )

        logger.debug("【新闻原始数据】\n" + json.dumps(news_data, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"新闻缓存读取/采集异常，降级到实时获取: {e}")
        try:
            news_data = get_all_trigger_news()
            logger.info("降级实时获取成功")
        except Exception as e2:
            logger.warning(f"实时获取也失败: {e2}")
            news_data = {"error": str(e2), "获取时间": today}

    # Step 2: Serper Web 搜索政策新闻（v1.1）
    logger.info("Serper Web 搜索政策新闻...")
    search_results = []
    try:
        search_results = search_multiple_queries()
        if search_results:
            logger.info(f"Serper 搜索返回 {len(search_results)} 条结果")
        else:
            logger.info("Serper 未启用或无结果")
    except Exception as e:
        logger.warning(f"Serper 搜索异常: {e}")

    # Step 3: 期货涨价检测（C4）
    logger.info("检测期货价格（C4）...")
    try:
        all_price_results = []
        for industry in COMMODITY_FUTURES_MAP:
            r = get_commodity_price_change(industry)
            all_price_results.append(r)
            status = "✅ 触发C4" if r["meets_c4"] else "  未触发"
            pct = (
                f"{r['max_pct_change_3m']}%"
                if r["max_pct_change_3m"] is not None
                else "无数据"
            )
            logger.info(f"  [{status}] {industry:<8} 近3月涨幅: {pct}")
        price_triggers = [r for r in all_price_results if r["meets_c4"]]
        logger.debug(
            "【期货价格检测详情】\n"
            + json.dumps(all_price_results, ensure_ascii=False, indent=2)
        )
    except Exception as e:
        logger.warning(f"期货价格检测异常: {e}")
        price_triggers = []

    # Step 4: 构建LLM输入
    price_summary = ""
    if price_triggers:
        price_summary = "\n\n【C4 期货涨价检测结果（Python规则，已确认满足≥20%）】\n"
        for item in price_triggers:
            price_summary += (
                f"- {item['industry']}：近3个月涨幅{item['max_pct_change_3m']}%"
                f"（合约：{', '.join(item['symbols'])}）\n"
            )
        price_summary += "以上行业已满足C4条件，请在分析时直接纳入涨价触发。"

    # 搜索结果摘要
    search_summary = ""
    if search_results:
        search_summary = "\n\n【Web 搜索政策新闻（Serper）】\n"
        for item in search_results[:20]:  # 最多取20条
            search_summary += (
                f"- [{item.get('date', '')}] {item.get('title', '')}：{item.get('snippet', '')[:100]}\n"
            )

    # 数据来源说明（缓存统计）
    cache_info = ""
    if isinstance(news_data, dict) and "采集统计" in news_data:
        stats = news_data.get("采集统计", {})
        cache_info = (
            f"\n\n【新闻数据来源说明】\n"
            f"数据来自当日采集缓存：共 {stats.get('总条数', 0)} 条，"
            f"时间跨度 {stats.get('时间跨度', 'N/A')}，"
            f"最近1小时新增 {stats.get('最近1小时新增', 0)} 条。\n"
            f"各来源条数：{stats.get('各来源条数', {})}"
        )

    # Step 4.5: 新闻过多时先分批压缩（v1.2）
    try:
        from tools.db import db as _db
        _content = _db.get_active_prompt("trigger", "system_prompt")
    except Exception:
        _content = None
    _trigger_prompt = _content if _content else TRIGGER_SYSTEM_PROMPT

    llm = build_llm()
    news_text, was_compressed = _compress_news_if_needed(news_data, llm)
    if was_compressed:
        cache_info += "\n⚠️ 新闻条数较多，已分批压缩为关键事件摘要后分析，上下文完整保留。"

    human_content = f"""今日日期：{today}

请分析以下新闻数据，识别满足触发条件的信息：
{cache_info}

{news_text}
{price_summary}
{search_summary}

请严格按照系统提示的JSON格式输出分析结果。
注意：对每条触发信息须评估新鲜度（freshness 字段）。"""

    # Step 5: 调用LLM
    logger.info("调用LLM分析触发条件...")

    logger.debug("【LLM 输入 - System Prompt】\n" + _trigger_prompt)
    logger.debug("【LLM 输入 - Human Message】\n" + human_content)

    messages = [
        SystemMessage(content=_trigger_prompt),
        HumanMessage(content=human_content),
    ]

    response = llm.invoke(messages)
    content = response.content
    logger.debug("【LLM 输出 - 原始响应】\n" + content)

    # Step 6: 解析JSON
    try:
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        result = json.loads(content)
    except Exception as e:
        logger.warning(f"JSON解析失败，使用原始文本: {e}")
        result = {
            "date": today,
            "has_triggers": False,
            "triggers": [],
            "raw_response": content,
            "parse_error": str(e),
        }

    result["date"] = today
    result["price_triggers_detected"] = len(price_triggers)

    # Step 7: 标记触发事件为已见（v1.1 新增）
    triggers = result.get("triggers", [])
    for trigger in triggers:
        try:
            # source 用受益行业标注，便于在去重历史中区分事件来源上下文
            industries = trigger.get("industries", [])
            source_label = "触发分析·" + "/".join(industries[:2]) if industries else "触发分析"
            event_tracker.mark_event_seen(
                event_summary=trigger.get("summary", ""),
                event_type=trigger.get("type", "未知"),
                source=source_label,
            )
        except Exception as e:
            logger.debug(f"标记事件失败（不影响主流程）: {e}")

    # Step 8: 保存触发结果到 DB（v1.2 新增）
    try:
        from tools.db import db
        db.save_triggers(today, triggers)
        logger.debug(f"触发结果已写入 DB：{len(triggers)} 条")
    except Exception as e:
        logger.warning(f"DB save_triggers 失败（不影响主流程）: {e}")

    logger.info(
        f"触发Agent完成：has_triggers={result.get('has_triggers')}, 触发数={len(triggers)}"
    )
    for i, t in enumerate(triggers, 1):
        logger.info(
            f"  触发[{i}] 类型={t.get('type')} 强度={t.get('strength')} "
            f"新鲜度={t.get('freshness', 'N/A')} 行业={t.get('industries')}"
        )
        logger.debug(
            f"  触发[{i}] 详情:\n" + json.dumps(t, ensure_ascii=False, indent=4)
        )

    logger.debug(
        "【触发Agent 最终输出】\n" + json.dumps(result, ensure_ascii=False, indent=2)
    )
    return result
