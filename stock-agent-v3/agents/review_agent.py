"""
Agent 3：每日复盘 Agent（v1.1 升级）
每日 15:35 运行，分析市场表现，验证当日推送，积累选股经验
v1.1: get_market_movers() 新增 retry/fallback 机制
输出：复盘日报（markdown格式）
"""

import json
import logging
import os
import time
from datetime import datetime, date

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import settings, build_llm as _build_llm
from tools.market_screener import get_market_movers, get_sector_performance

logger = logging.getLogger(__name__)

# ── 可编辑部分（Critic Agent 可修改） ────────────────────────────────────────
_REVIEW_EDITABLE = """你是一个A股市场的每日复盘分析师。在每天收盘后运行，独立分析市场真实表现，并与当日推送的选股结果交叉验证。

**任务一：市场热点复盘**
分析今日A股涨幅前50、跌幅前50的股票。

对涨幅前50，识别：
1. 涨幅较大的股票集中在哪些行业板块？
2. 这些股票是否有共同的驱动因素（政策/产品涨价/转折事件）？
3. 这个驱动因素是一次性的还是有持续性的？
   - 持续性判断标准：是否有后续政策跟进？供需结构是否发生根本改变？机构是否持续介入？
   - 一次性信号：仅凭领导人讲话、无具体措施的意见稿、单纯的游资炒作

对跌幅前50，识别：
1. 是否有系统性风险（大盘整体下跌）还是行业性利空？
2. 对正在跟踪的股票是否有影响？

**任务二：验证当日推送**
对今日触发Agent推送的股票，核查：
1. 市场实际反应如何（涨/跌/平，成交量变化）？
2. 市场反应是否与推荐逻辑吻合？
3. 如果市场没有反应或反向运动，可能的原因是什么？
4. 该持续跟踪还是暂时观望？

**任务三：经验积累**
每周五额外输出：
- 本周哪类触发信息预测准确率最高？
- 哪类信息容易产生误判？
- 有哪些未被触发Agent捕捉到但市场有强烈反应的事件？"""

# ── 固定输出格式（系统内置，不可修改） ──────────────────────────────────────
_REVIEW_OUTPUT_FORMAT = """**输出格式（Markdown，请严格按此结构输出）**
# 每日复盘 - {date}

## 1. 今日市场概况
（大盘指数、成交量、板块轮动方向）

## 2. 热点板块分析
（Top 3板块 + 驱动因素 + 持续性判断）

## 3. 当日推送验证
（每只股票：名称-实际涨跌-成交量变化-验证结论）

## 4. 今日发现
（市场上有强烈反应但未被系统捕捉的机会，简要分析原因）

## 5. 明日关注
（基于今日复盘，明日重点观察的信号）

## 6. 本周经验积累（仅周五）
（本周复盘总结）

**判断原则**
政策要有实质性措施才可能有持续性；
只有领导人讲话没有具体措施，通常是一两天行情；
行业整治类政策（限制供给）往往比补贴类政策（扩大需求）更有持续性；
上下游轮动有规律：核心行业先涨，原材料上游随后，耗材下游最后。"""

# 完整提示词（代码常量后备，运行时以 DB 为准）
REVIEW_SYSTEM_PROMPT = _REVIEW_EDITABLE + "\n\n" + _REVIEW_OUTPUT_FORMAT

# ── 触发检测优化 — 可编辑部分 ────────────────────────────────────────────────
_TRIGGER_REVIEW_EDITABLE = """你是一个A股信息触发系统的优化分析师。你会收到今日市场完整行情数据（涨幅前50、跌幅前50、板块涨跌幅）以及今日触发Agent的检测结果（检测到的触发事件，或无触发的说明）。

**你的任务**：对比市场实际热点与触发Agent的检测结果，评估触发Agent的信息识别能力，并生成改进版触发Agent提示词。

**分析维度**：
1. **漏报分析**：今日市场有强烈反应的板块/主题，触发Agent是否在早盘扫描中捕捉到了对应信号？
   - 如果有漏报，分析原因：判断标准太严格？信息来源覆盖不足？触发类型定义遗漏？新鲜度阈值过高？
2. **命中分析**：触发Agent检测到的事件，市场是否确实有对应反应？
   - 无反应或反向运动的，分析是误报原因还是时间滞后问题
3. **改进方向**：基于漏报和误报，具体指出判断准则中需要修改的文字描述"""

# ── 触发检测优化 — 固定输出格式（含哨兵分隔符，后端解析依赖，不可修改） ──
_TRIGGER_REVIEW_OUTPUT_FORMAT = """**输出格式（按此结构输出，然后附上改进版Prompt）**

## 触发检测效果评估

### 漏报分析
（列举今日市场明显但未被触发的信号，每条说明原因）

### 命中情况
（简评今日触发事件与市场实际表现的对应关系）

### 改进建议
（至少2条具体建议，说明对应触发Prompt中哪段文字需要如何改动）

---SUGGESTED_TRIGGER_PROMPT_BELOW---
（此处输出改进版触发Agent提示词的可编辑分析准则部分，保持C1政策/C4涨价/C6转折三类框架结构不变，只修改判断标准描述和示例，JSON格式模板由系统自动追加）"""


def build_llm():
    return _build_llm("review")


def _get_market_movers_with_retry(top_n: int = 50, max_retries: int = 2, retry_delay: float = 5.0) -> dict:
    """
    获取市场行情数据，带 retry/fallback 机制（v1.1 新增）

    Args:
        top_n: 涨跌幅榜数量
        max_retries: 最大重试次数（默认2次，即首次+1次重试）
        retry_delay: 重试间隔秒数

    Returns:
        市场行情数据字典；若所有重试均失败，返回最小化数据并注明错误
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            data = get_market_movers(top_n=top_n)
            if data.get("error"):
                raise RuntimeError(data["error"])
            logger.info(
                f"市场行情获取成功（第{attempt + 1}次尝试）"
            )
            return data
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(
                    f"市场行情获取失败（第{attempt + 1}次）: {e}，{retry_delay}秒后重试..."
                )
                time.sleep(retry_delay)
            else:
                logger.warning(
                    f"市场行情获取失败（第{attempt + 1}次，已达最大重试次数）: {e}"
                )

    # Fallback：返回最小化市场数据
    logger.warning("使用最小化市场数据 fallback")
    return {
        "获取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "涨幅前50": [],
        "跌幅前50": [],
        "市场概况": {},
        "error": f"市场数据获取失败（已重试{max_retries}次）: {last_error}",
        "fallback": True,
    }


def run_review_agent(daily_push=None) -> dict:
    """
    运行复盘Agent：
    1. 获取市场行情数据（带retry，v1.1）
    2. 读取当日推送记录
    3. 调用LLM生成复盘日报
    4. 返回markdown格式日报

    Args:
        daily_push: 当日推送记录（trigger_result + screener_result），可为None
    """
    logger.info("=== 复盘Agent 启动 (v1.1) ===")
    today = datetime.now().strftime("%Y-%m-%d")
    today_weekday = date.today().weekday()  # 0=周一，4=周五
    is_friday = today_weekday == 4

    # Step 1: 获取市场数据（带retry）
    logger.info("获取市场行情数据...")
    market_data = _get_market_movers_with_retry(top_n=50)

    ov = market_data.get("市场概况", {})
    gainers = market_data.get("涨幅前50", [])
    losers = market_data.get("跌幅前50", [])

    if market_data.get("fallback"):
        logger.warning("⚠️ 使用 fallback 市场数据，复盘报告将注明数据缺失")
    else:
        logger.info(
            f"市场概况: 上涨={ov.get('上涨家数', 'N/A')} 下跌={ov.get('下跌家数', 'N/A')} "
            f"均涨跌={ov.get('平均涨跌幅(%)', 'N/A')}% 情绪={ov.get('市场情绪', 'N/A')}"
        )
        if gainers:
            top5 = [(s["名称"], s["涨跌幅(%)"]) for s in gainers[:5]]
            logger.info(f"涨幅前5: {top5}")
        if losers:
            bot5 = [(s["名称"], s["涨跌幅(%)"]) for s in losers[:5]]
            logger.info(f"跌幅前5: {bot5}")

    logger.debug(
        "【市场行情原始数据】\n" + json.dumps(market_data, ensure_ascii=False, indent=2)
    )

    sector_data = []
    try:
        sector_data = get_sector_performance()
        if sector_data:
            top3 = [(s["板块名称"], s["涨跌幅(%)"]) for s in sector_data[:3]]
            bot3 = [(s["板块名称"], s["涨跌幅(%)"]) for s in sector_data[-3:]]
            logger.info(f"板块涨幅前3: {top3}")
            logger.info(f"板块跌幅后3: {bot3}")
        logger.debug(
            "【板块数据原始】\n"
            + json.dumps(sector_data[:20], ensure_ascii=False, indent=2)
        )
    except Exception as e:
        logger.warning(f"板块数据获取失败: {e}")

    # Step 2: 整理推送记录
    if daily_push:
        push_top20 = (daily_push.get("screener_result") or {}).get("top20", [])
        logger.info(f"当日推送记录: 精筛Top={len(push_top20)} 家")
        if push_top20:
            logger.info(
                f"  推送股票: {[(s.get('name'), s.get('code')) for s in push_top20[:5]]}..."
            )
        push_summary = (
            f"\n\n【当日推送记录】\n{json.dumps(daily_push, ensure_ascii=False, indent=2)}"
        )
    else:
        logger.info("当日无推送记录（未运行触发Agent或无触发）")
        push_summary = "\n\n【当日推送记录】\n今日未运行触发Agent或无触发信息，请在复盘中标注。"

    # Step 3: 构建LLM输入
    market_text = json.dumps(market_data, ensure_ascii=False, indent=2)
    sector_text = json.dumps(
        sector_data[:20] if sector_data else [], ensure_ascii=False, indent=2
    )

    fallback_note = ""
    if market_data.get("fallback"):
        fallback_note = "\n⚠️ 注意：市场行情数据获取失败，以下分析基于有限数据，请在报告中注明数据来源受限。"

    friday_note = "\n注意：今天是周五，请额外输出【本周经验积累】部分。" if is_friday else ""

    human_content = f"""今日日期：{today}（{'周五' if is_friday else '工作日'}）{friday_note}{fallback_note}

【今日市场行情】
{market_text}

【板块涨跌幅（前20板块）】
{sector_text}
{push_summary}

请按照系统提示的Markdown格式，生成今日完整复盘报告。"""

    # Step 4: 调用LLM
    logger.info("调用LLM生成复盘日报...")
    logger.debug("【LLM 输入 - 复盘 Human Message】\n" + human_content)

    try:
        from tools.db import db as _db
        _editable = _db.get_active_prompt("review", "system_prompt") or _REVIEW_EDITABLE
        _db.seed_output_format("review", _REVIEW_OUTPUT_FORMAT)
        _fmt = _db.get_output_format("review") or _REVIEW_OUTPUT_FORMAT
    except Exception:
        _editable, _fmt = _REVIEW_EDITABLE, _REVIEW_OUTPUT_FORMAT
    _review_prompt = _editable + "\n\n" + _fmt

    llm = build_llm()
    messages = [
        SystemMessage(content=_review_prompt),
        HumanMessage(content=human_content),
    ]

    response = llm.invoke(messages)
    review_content = response.content
    logger.debug("【LLM 输出 - 复盘日报原始响应】\n" + review_content)

    result = {
        "date": today,
        "is_friday": is_friday,
        "review_markdown": review_content,
        "market_overview": market_data.get("市场概况", {}),
        "top_sectors": sector_data[:5] if sector_data else [],
        "market_data_fallback": market_data.get("fallback", False),
    }

    # Step 5: 生成触发检测改进建议（第二次 LLM 调用）
    logger.info("生成触发检测优化建议...")
    try:
        from agents.trigger_agent import _TRIGGER_EDITABLE as _te_default
        current_trigger_editable = _db.get_active_prompt("trigger", "system_prompt") or _te_default

        # 记录当前激活的 trigger prompt id（供回滚用）
        previous_trigger_prompt_id = None
        for v in _db.list_prompt_versions("trigger"):
            if v.get("prompt_name") == "system_prompt" and v.get("is_active"):
                previous_trigger_prompt_id = v["id"]
                break

        _db.seed_output_format("trigger_review", _TRIGGER_REVIEW_OUTPUT_FORMAT)
        _trigger_review_fmt = _db.get_output_format("trigger_review") or _TRIGGER_REVIEW_OUTPUT_FORMAT
        _trigger_review_system = _TRIGGER_REVIEW_EDITABLE + "\n\n" + _trigger_review_fmt

        trigger_human = (
            f"今日日期：{today}\n\n"
            f"【今日触发Agent检测结果】\n{push_summary}\n\n"
            f"【今日市场行情】\n"
            + json.dumps(market_data, ensure_ascii=False, indent=2)
            + "\n\n【板块涨跌幅（前20板块）】\n"
            + json.dumps(sector_data[:20] if sector_data else [], ensure_ascii=False, indent=2)
            + "\n\n---\n## 当前触发Agent提示词可编辑部分（请在此基础上修改，不要大幅重写）\n\n"
            + f"```\n{current_trigger_editable}\n```\n\n"
            + "⚠️ 注意：JSON输出格式模板由系统自动追加，你只需输出可编辑的分析准则部分。"
        )

        llm2 = build_llm()
        resp2 = llm2.invoke([
            SystemMessage(content=_trigger_review_system),
            HumanMessage(content=trigger_human),
        ])
        raw2 = resp2.content
        logger.debug("【LLM 输出 - 触发检测优化原始响应】\n" + raw2)

        _trigger_separator = "---SUGGESTED_TRIGGER_PROMPT_BELOW---"
        if _trigger_separator in raw2:
            parts2 = raw2.split(_trigger_separator, 1)
            trigger_review_markdown = parts2[0].strip()
            suggested_trigger_prompt = parts2[1].strip()
        else:
            trigger_review_markdown = raw2.strip()
            suggested_trigger_prompt = None
            logger.warning("[复盘Agent] 未找到触发检测分隔符，无法提取改进 Prompt")

        auto_activate = os.getenv(
            "REVIEW_TRIGGER_AUTO_ACTIVATE",
            _db.get_config("review_trigger_auto_activate", "false")
        ).strip().lower() == "true"

        suggested_trigger_prompt_id = None
        if suggested_trigger_prompt:
            suggested_trigger_prompt_id = _db.save_prompt(
                "trigger", "system_prompt", suggested_trigger_prompt,
                note=f"复盘优化 | {today}{'（已激活）' if auto_activate else ''}",
                active=auto_activate,
                source="review",
            )
            logger.info(
                f"[复盘Agent] 触发检测改进 Prompt 已保存 id={suggested_trigger_prompt_id}，"
                f"{'自动激活' if auto_activate else '待人工审核'}"
            )

        result["suggested_trigger_prompt"] = suggested_trigger_prompt
        result["suggested_trigger_prompt_id"] = suggested_trigger_prompt_id
        result["previous_trigger_prompt_id"] = previous_trigger_prompt_id
        result["trigger_review_markdown"] = trigger_review_markdown
    except Exception as e:
        logger.warning(f"[复盘Agent] 触发检测优化分析失败（不影响主复盘）: {e}", exc_info=True)

    # 保存复盘结果到 DB（v1.2 新增）
    try:
        from tools.db import db
        db.save_review(today, result)
        logger.debug("复盘报告已写入 DB")
    except Exception as e:
        logger.warning(f"DB save_review 失败（不影响主流程）: {e}")

    logger.info("复盘Agent完成")
    return result
