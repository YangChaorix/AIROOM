"""
Agent 1 — 事件触发扫描（每日 09:15 运行）

流程：
  [Python] 拉取今日新闻（同花顺 + CCTV）
  [Python] 期货价格扫描 → C4 条件判断
  [Python] 关键词预过滤候选新闻（发改委/工信部/制裁/整治等）
  [LLM×1] 对候选新闻判断 C1/C6，输出受益行业和公司

触发条件：
  C1 — 政策利好（发改委/工信部/国务院等政策文件）
  C4 — 商品涨价（期货近3个月涨幅≥20%）
  C6 — 转折催化剂（制裁/限产/事故/新品发布等突发事件）
"""

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agents.news_scanner_agent import INDUSTRY_KEYWORD_MAP, fetch_todays_news
from config.settings import settings
from tools.price_monitor import scan_all_industry_prices


# ─── 关键词预过滤 ─────────────────────────────────────────────────────────────
# 命中任意一词的新闻标题将进入 LLM 精判
C1_C6_KEYWORDS = [
    # 政策类（C1）
    "发改委", "工信部", "国务院", "财政部", "央行", "商务部",
    "政策", "补贴", "扶持", "专项", "规划", "条例", "办法",
    "降息", "降准", "LPR", "利率", "货币政策",
    # 供需/涨价类（C4 文字补充）
    "涨价", "提价", "价格上涨", "供应紧张", "短缺", "限产",
    "碳酸锂", "稀土", "铜价", "铝价", "煤价", "油价",
    # 转折催化剂（C6）
    "制裁", "断供", "禁止出口", "反倾销", "反补贴",
    "整治", "整改", "查处", "违规", "事故",
    "突破", "新品", "发布", "首发", "量产", "投产",
    "并购", "重组", "定增", "回购",
]


TRIGGER_SYSTEM_PROMPT = """你是A股事件驱动投资的专业分析师，擅长从政策/供需/市场事件中识别受益方向。

你的任务是分析今日新闻，判断是否触发以下投资条件：

**C1 — 政策利好**：发改委/工信部/国务院等出台明确的产业扶持政策，有具体补贴/规划/准入放开
**C6 — 转折催化剂**：制裁/限产/重大技术突破/行业整合等，能改变供需格局的突发事件

分析要求：
1. 逐条审阅候选新闻，判断是否真实构成 C1 或 C6 触发
2. 识别直接受益的行业（优先级：细分行业 > 大行业）
3. 识别具体受益公司名称（非代码，需是真实A股上市公司）
4. 给出置信度判断：高/中/低

请严格以JSON格式输出（不要有其他文字）：
{
  "triggered": true/false,
  "hit_conditions": ["C1", "C6"],
  "condition_details": {
    "C1": {
      "triggered": true/false,
      "evidence": "触发依据（引用新闻原文关键句）",
      "confidence": "高/中/低"
    },
    "C6": {
      "triggered": true/false,
      "evidence": "触发依据",
      "confidence": "高/中/低"
    }
  },
  "affected_industries": ["行业1", "行业2"],
  "affected_companies": ["公司名1", "公司名2"],
  "trigger_summary": "100字以内摘要，描述核心事件和受益逻辑，供Agent2使用"
}

注意：
- 日常例行新闻（如日常产量数据、非政策性表态）不应触发
- 只有明确利好、有行动力的政策才触发C1
- 触发条件要求"超预期"，普通新闻不触发
"""


def _filter_candidate_news(titles: list[str]) -> list[str]:
    """
    用关键词预过滤，筛选出可能触发 C1/C6 的候选新闻标题

    Returns:
        命中关键词的标题列表（去重，最多50条）
    """
    candidates = []
    seen = set()
    for title in titles:
        if title in seen:
            continue
        for kw in C1_C6_KEYWORDS:
            if kw in title:
                candidates.append(title)
                seen.add(title)
                break
    return candidates[:50]


async def run_trigger_agent() -> dict[str, Any]:
    """
    执行 Agent 1：事件触发扫描

    Returns:
        TriggerResult 字典：
        {
            "triggered": bool,
            "hit_conditions": list[str],        # ["C1", "C4", "C6"] 子集
            "affected_industries": list[str],
            "affected_companies": list[str],
            "c4_price_data": list[dict],
            "trigger_summary": str,
            "raw_news_count": int,
            "candidate_news_count": int,
        }
    """
    print("\n[Agent 1] 开始事件触发扫描...")

    # ── Step 1: 获取今日新闻 ─────────────────────────────────
    print("  [Step 1] 拉取今日新闻（同花顺 + CCTV）...")
    news_data = fetch_todays_news()
    all_titles = news_data["titles"]
    print(f"  → 获取到 {len(all_titles)} 条新闻标题")

    # ── Step 2: C4 期货价格扫描 ──────────────────────────────
    print("  [Step 2] 扫描商品期货价格（C4 条件）...")
    c4_data = scan_all_industry_prices()
    c4_industries = [item["industry"] for item in c4_data]
    if c4_industries:
        print(f"  → C4 触发行业：{c4_industries}")
    else:
        print("  → C4 无触发（近3个月商品涨幅均未达20%）")

    # ── Step 3: 关键词预过滤 ─────────────────────────────────
    print("  [Step 3] 关键词预过滤候选新闻...")
    candidates = _filter_candidate_news(all_titles)
    print(f"  → 候选新闻 {len(candidates)} 条（从 {len(all_titles)} 条中筛选）")

    # 如果无候选新闻且无C4触发，直接返回不触发
    if not candidates and not c4_data:
        print("  → 无触发事件，跳过 LLM 分析")
        return {
            "triggered": False,
            "hit_conditions": [],
            "affected_industries": [],
            "affected_companies": [],
            "c4_price_data": [],
            "trigger_summary": "今日无明显触发事件",
            "raw_news_count": len(all_titles),
            "candidate_news_count": 0,
        }

    # ── Step 4: LLM 判断 C1/C6 ──────────────────────────────
    print("  [Step 4] LLM 分析候选新闻（C1/C6 判断）...")

    candidate_text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(candidates))
    c4_text = ""
    if c4_data:
        c4_lines = [
            f"- {item['industry']}：近3个月最大涨幅 {item['max_pct_change_3m']:.1f}%"
            for item in c4_data
        ]
        c4_text = "\n\n**C4 期货价格涨幅超20%（已确认触发）：**\n" + "\n".join(c4_lines)

    user_message = f"""请分析以下今日候选新闻，判断是否触发 C1（政策利好）或 C6（转折催化剂）条件：

**候选新闻标题（{len(candidates)}条）：**
{candidate_text}
{c4_text}

今日日期：{__import__('datetime').date.today().isoformat()}

请输出JSON格式的分析结果。"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=0.1,
        max_tokens=1000,
    )

    messages = [
        SystemMessage(content=TRIGGER_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    response = await llm.ainvoke(messages)
    analysis_text = response.content

    # 解析 LLM 输出
    try:
        json_match = re.search(r'\{[\s\S]*\}', analysis_text)
        if json_match:
            llm_result = json.loads(json_match.group())
        else:
            llm_result = {"triggered": False, "hit_conditions": [], "trigger_summary": "LLM输出解析失败"}
    except json.JSONDecodeError:
        llm_result = {"triggered": False, "hit_conditions": [], "trigger_summary": "LLM输出解析失败"}

    # ── 汇总结果 ────────────────────────────────────────────
    hit_conditions = list(llm_result.get("hit_conditions", []))
    if c4_data and "C4" not in hit_conditions:
        hit_conditions.append("C4")

    # C4 触发的行业并入受益行业列表
    affected_industries = list(llm_result.get("affected_industries", []))
    for ind in c4_industries:
        if ind not in affected_industries:
            affected_industries.append(ind)

    triggered = llm_result.get("triggered", False) or bool(c4_data)

    trigger_summary = llm_result.get("trigger_summary", "")
    if c4_data and trigger_summary:
        trigger_summary += f" | C4: {', '.join(c4_industries)}期货价格近3月涨幅超20%"
    elif c4_data:
        trigger_summary = f"C4触发：{', '.join(c4_industries)}期货价格近3月涨幅超20%"

    result = {
        "triggered": triggered,
        "hit_conditions": hit_conditions,
        "affected_industries": affected_industries,
        "affected_companies": llm_result.get("affected_companies", []),
        "c4_price_data": c4_data,
        "trigger_summary": trigger_summary,
        "raw_news_count": len(all_titles),
        "candidate_news_count": len(candidates),
        "llm_detail": llm_result,
    }

    print(f"  → 触发状态：{'✓ 已触发' if triggered else '✗ 未触发'}")
    if triggered:
        print(f"  → 命中条件：{hit_conditions}")
        print(f"  → 受益行业：{affected_industries}")
        print(f"  → 受益公司：{result['affected_companies']}")

    return result
