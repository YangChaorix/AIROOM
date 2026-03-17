"""
Agent 1：信息触发 Agent
每日 09:15 运行，扫描三类触发条件（C1/C4/C6）
输出：命中信息 + 受影响行业/企业列表（JSON）
"""

import json
import logging
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import settings
from tools.news_tools import get_all_trigger_news
from tools.price_monitor import scan_all_industry_prices

logger = logging.getLogger(__name__)

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

**输出格式**
对每条触发信息，输出：
1. 信息摘要（2-3句，注明来源和发布时间）
2. 触发类型（政策/涨价/转折事件）
3. 直接受益行业（最核心受益的行业，1-3个）
4. 可能受益企业范围（包括上游原材料、核心制造、下游应用，各列2-3家）
5. 影响强度评估（强/中/弱）+ 判断理由
6. 注意事项（例如：政策力度待观察；涨价可能是短期现象等）

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
      "caution": "注意事项"
    }
  ],
  "summary": "今日触发情况简述"
}"""


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        model=settings.deepseek.model_name,
        temperature=settings.deepseek.temperature,
        max_tokens=settings.deepseek.max_tokens,
    )


def run_trigger_agent() -> dict:
    """
    运行触发Agent：
    1. 采集新闻数据
    2. 检测期货涨价（C4）
    3. 调用LLM分析触发条件
    4. 返回触发结果
    """
    logger.info("=== 触发Agent 启动 ===")
    today = datetime.now().strftime("%Y-%m-%d")

    # Step 1: 采集新闻
    logger.info("采集新闻数据...")
    try:
        news_data = get_all_trigger_news()
        macro_count = len(news_data.get("今日宏观政策新闻", []))
        policy_count = len(news_data.get("财经政策资讯", []))
        logger.info(f"新闻采集完成：宏观快讯 {macro_count} 条，财经政策 {policy_count} 条")
        logger.debug("【新闻原始数据】\n" + json.dumps(news_data, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"新闻采集异常: {e}")
        news_data = {"error": str(e), "获取时间": today}

    # Step 2: 期货涨价检测（C4）
    logger.info("检测期货价格（C4）...")
    try:
        from tools.price_monitor import COMMODITY_FUTURES_MAP, get_commodity_price_change
        all_price_results = []
        for industry in COMMODITY_FUTURES_MAP:
            r = get_commodity_price_change(industry)
            all_price_results.append(r)
            status = "✅ 触发C4" if r["meets_c4"] else "  未触发"
            pct = f"{r['max_pct_change_3m']}%" if r["max_pct_change_3m"] is not None else "无数据"
            logger.info(f"  [{status}] {industry:<8} 近3月涨幅: {pct}")
        price_triggers = [r for r in all_price_results if r["meets_c4"]]
        logger.debug("【期货价格检测详情】\n" + json.dumps(all_price_results, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"期货价格检测异常: {e}")
        price_triggers = []

    # Step 3: 构建LLM输入
    price_summary = ""
    if price_triggers:
        price_summary = "\n\n【C4 期货涨价检测结果（Python规则，已确认满足≥20%）】\n"
        for item in price_triggers:
            price_summary += (
                f"- {item['industry']}：近3个月涨幅{item['max_pct_change_3m']}%"
                f"（合约：{', '.join(item['symbols'])}）\n"
            )
        price_summary += "以上行业已满足C4条件，请在分析时直接纳入涨价触发。"

    news_text = json.dumps(news_data, ensure_ascii=False, indent=2)
    human_content = f"""今日日期：{today}

请分析以下新闻数据，识别满足触发条件的信息：

{news_text}
{price_summary}

请严格按照系统提示的JSON格式输出分析结果。"""

    # Step 4: 调用LLM
    logger.info("调用LLM分析触发条件...")
    logger.debug("【LLM 输入 - System Prompt】\n" + TRIGGER_SYSTEM_PROMPT)
    logger.debug("【LLM 输入 - Human Message】\n" + human_content)

    llm = build_llm()
    messages = [
        SystemMessage(content=TRIGGER_SYSTEM_PROMPT),
        HumanMessage(content=human_content),
    ]

    response = llm.invoke(messages)
    content = response.content
    logger.debug("【LLM 输出 - 原始响应】\n" + content)

    # Step 5: 解析JSON
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

    triggers = result.get("triggers", [])
    logger.info(f"触发Agent完成：has_triggers={result.get('has_triggers')}, 触发数={len(triggers)}")
    for i, t in enumerate(triggers, 1):
        logger.info(f"  触发[{i}] 类型={t.get('type')} 强度={t.get('strength')} "
                    f"行业={t.get('industries')}")
        logger.debug(f"  触发[{i}] 详情:\n" + json.dumps(t, ensure_ascii=False, indent=4))

    logger.debug("【触发Agent 最终输出】\n" + json.dumps(result, ensure_ascii=False, indent=2))
    return result
