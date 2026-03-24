"""
Agent 2：企业精筛 Agent（v1.1 升级）
输入：trigger_agent 输出的触发结果（行业/企业列表）
输出：6维度评分 Top 20 企业（JSON + markdown）
v1.1: 维度2 新增成本传导判断（原材料涨价时的下游成本承压方 D2=0）
"""

import json
import logging
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import settings, build_llm as _build_llm
from tools.stock_data import get_stock_basic_info, get_financial_indicators, get_historical_volume
from tools.shareholder_tools import get_top_shareholders, get_shareholder_changes
from tools.technical_tools import calc_volume_breakthrough, calc_long_term_trend

logger = logging.getLogger(__name__)

SCREENER_SYSTEM_PROMPT = """你是一个A股企业基本面分析师。你会收到一份今日触发的行业和企业列表，需要对其中每家企业从多个维度进行分析评分，筛选出最值得关注的Top 20。

**输入**：触发Agent输出的行业/企业列表 + 当日触发原因 + 各企业量化数据

**分析维度（每项0-3分，满分18分）**

【维度1：行业龙头地位】（0-3分）
- 3分：主营产品市场份额全国或全球前3，且主营产品占公司总营收70%以上
- 2分：行业前5，主营产品占营收50%-70%
- 1分：行业前10，或主营产品占比较低
- 0分：非行业核心企业
- 数据来源：公司年报、同花顺公司概况

【维度2：主营产品受益程度】（0-3分）
- 3分：政策/事件直接针对该公司主营产品，且该产品营收占比高，毛利率有望大幅提升
- 2分：间接受益，或主营产品受益但占比一般
- 1分：边缘受益（上下游关联，影响有限）
- 0分：受益逻辑牵强，或实为成本承压方（如原材料涨价时的下游制造企业）
- ⚠️ 特别注意：原材料/能源涨价时，航空、化纤、炼化、橡胶制品、包装等下游行业是成本承压方，D2应评0分
  - 铜/铝涨价时：线缆、家电、汽车制造等以铜铝为原料的企业是成本承压方，D2=0
  - 煤炭/天然气涨价时：航空、发电、化工下游是成本承压方，D2=0
  - 原油涨价时：炼化下游、化纤、航空是成本承压方，D2=0

【维度3：股东结构（稳定性信号）】（0-3分）
- 3分：前10大流通股股东以私募基金+个人大股东为主，连续3个季度未减仓甚至加仓，合计占流通股60%以上
- 2分：满足持仓稳定条件，但占比在40%-60%之间
- 1分：机构持仓为主但持仓稳定
- 0分：股东结构不符合或无法查证
- 数据来源：同花顺十大流通股东（已提供量化数据）

【维度4：中长期上涨趋势】（0-3分）
- 3分：未来6-12个月有清晰的持续性需求增长逻辑，且行业已进入上行周期
- 2分：有一定持续性，但存在不确定因素
- 1分：短期有利好，中长期不确定
- 0分：仅为一次性利好，无持续性
- 判断方式：根据行业政策延续性、需求增长曲线、同类历史案例判断

【维度5：技术突破信号】（0-3分）
- 3分：近3日日均交易量较过去20日环比增长5倍以上，日/周换手率明显放大，股价突破近期高点
- 2分：成交量放大2-5倍，但突破信号不明显
- 1分：成交量小幅放大，无明显突破
- 0分：缩量或无明显变化
- 数据来源：量化数据已提供，请参考d5_score字段

【维度6：估值合理性】（0-3分，加分项）
- 重点关注：过去好几年没涨过、股价长期横盘、近期才开始启动的票
- 这类票往往是大股东在默默建仓，一旦启动往往涨幅巨大

**输出格式**
按总分排序，输出Top 20企业，每家包括：
1. 企业名称 + 股票代码
2. 触发原因（对应哪条初筛信息）
3. 各维度得分 + 简短理由（1句话）
4. 总分 + 综合推荐理由（3-5句话）
5. 风险提示（该股票主要风险点）

**重要提示**
- 如果一家企业触发多条初筛信息，适当加权
- 龙头企业通常比中小企业先反应，但中小企业弹性更大——请在推荐理由中说明
- 永安药业案例参考：美国FDA政策→全球牛磺酸需求扩大→永安药业占全球70%市场份额→主营产品直接受益→这才是真正的精准匹配
- 成本传导特别注意：原材料上涨时，不要把成本承压的下游企业评为高受益（D2=0）

**请以JSON格式输出**，结构如下：
{
  "date": "YYYY-MM-DD",
  "top20": [
    {
      "rank": 1,
      "name": "企业名称",
      "code": "股票代码",
      "trigger_reason": "触发原因",
      "scores": {
        "D1_龙头地位": {"score": 3, "reason": "简短理由"},
        "D2_受益程度": {"score": 3, "reason": "简短理由"},
        "D3_股东结构": {"score": 2, "reason": "简短理由"},
        "D4_上涨趋势": {"score": 2, "reason": "简短理由"},
        "D5_技术突破": {"score": 3, "reason": "简短理由"},
        "D6_估值合理": {"score": 1, "reason": "简短理由"}
      },
      "total_score": 14,
      "recommendation": "综合推荐理由（3-5句话）",
      "risk": "主要风险点"
    }
  ],
  "analysis_summary": "本次精筛总体说明"
}"""


def build_llm():
    return _build_llm("screener")


def _collect_company_data(company_name: str, stock_code: str) -> dict:
    """为精筛Agent收集企业量化数据"""
    data = {"名称": company_name, "代码": stock_code}

    logger.debug(f"  [数据采集] {company_name}({stock_code}) - 基本信息")
    try:
        info = get_stock_basic_info(stock_code)
        data["基本信息"] = info
        logger.debug(
            f"    基本信息: 行业={info.get('行业', 'N/A')} 总市值={info.get('总市值(亿)', 'N/A')}亿 "
            f"今日涨跌={info.get('今日涨跌幅(%)', 'N/A')}%"
        )
    except Exception as e:
        data["基本信息_error"] = str(e)
        logger.debug(f"    基本信息获取失败: {e}")

    logger.debug(f"  [数据采集] {company_name}({stock_code}) - 财务指标")
    try:
        fin = get_financial_indicators(stock_code)
        data["财务指标"] = fin
        recent = (fin.get("财务摘要(近4期)") or [{}])[0]
        logger.debug(
            f"    最新财务: 净利率={recent.get('净利率', 'N/A')} "
            f"毛利率={recent.get('毛利率', 'N/A')} EPS={recent.get('基本每股收益', 'N/A')}"
        )
    except Exception as e:
        data["财务指标_error"] = str(e)
        logger.debug(f"    财务指标获取失败: {e}")

    logger.debug(f"  [数据采集] {company_name}({stock_code}) - 股东结构(D3)")
    try:
        holder = get_top_shareholders(stock_code)
        data["股东结构"] = holder
        cs = holder.get("筹码结构分析", {})
        logger.debug(
            f"    私募+个人={cs.get('私募+个人持股(%)', 'N/A')}% "
            f"D3得分={cs.get('D3得分', 'N/A')} {cs.get('D3描述', '')}"
        )
    except Exception as e:
        data["股东结构_error"] = str(e)
        logger.debug(f"    股东结构获取失败: {e}")

    logger.debug(f"  [数据采集] {company_name}({stock_code}) - 技术突破(D5)")
    try:
        tech = calc_volume_breakthrough(stock_code)
        data["技术突破D5"] = tech
        logger.debug(
            f"    量比={tech.get('量比(3日/20日)', 'N/A')}x "
            f"D5得分={tech.get('d5_score', 'N/A')} {tech.get('d5_desc', '')}"
        )
    except Exception as e:
        data["技术突破_error"] = str(e)
        logger.debug(f"    技术突破获取失败: {e}")

    logger.debug(f"  [数据采集] {company_name}({stock_code}) - 中长期趋势(D4辅助)")
    try:
        trend = calc_long_term_trend(stock_code)
        data["中长期趋势D4"] = trend
        logger.debug(
            f"    近6月涨幅={trend.get('近6个月涨幅(%)', 'N/A')}% "
            f"MA60={trend.get('MA60', 'N/A')} 趋势={trend.get('趋势描述', '')}"
        )
    except Exception as e:
        data["趋势分析_error"] = str(e)
        logger.debug(f"    趋势分析获取失败: {e}")

    logger.debug(
        f"  [数据采集完成] {company_name}({stock_code})\n"
        + json.dumps(data, ensure_ascii=False, indent=4, default=str)
    )
    return data


def _extract_companies_from_triggers(trigger_result: dict) -> list[dict]:
    """从触发Agent结果中提取企业列表（含股票代码）"""
    companies = []
    seen = set()
    for trigger in trigger_result.get("triggers", []):
        for category, company_list in trigger.get("companies", {}).items():
            for company in company_list:
                if isinstance(company, dict):
                    name = company.get("name", "")
                    code = company.get("code", "")
                else:
                    name = str(company)
                    code = ""
                    if "(" in name and ")" in name:
                        parts = name.split("(")
                        name = parts[0].strip()
                        code = parts[1].rstrip(")").strip()

                key = code or name
                if key and key not in seen:
                    seen.add(key)
                    companies.append(
                        {
                            "name": name,
                            "code": code,
                            "trigger_type": trigger.get("type", ""),
                            "industry": ", ".join(trigger.get("industries", [])),
                        }
                    )
    return companies


def _parse_screener_json(content: str, today: str) -> dict:
    """
    容错解析精筛Agent的JSON输出：
    1. 提取 markdown 代码块
    2. 尝试直接 json.loads
    3. 若失败（通常是 max_tokens 截断），逐个提取完整的 top20 条目重建 JSON
    """
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 截断修复：提取 top20 数组里所有完整的条目
    try:
        arr_start = content.find('"top20"')
        if arr_start == -1:
            raise ValueError("no top20")
        bracket_start = content.find("[", arr_start)
        if bracket_start == -1:
            raise ValueError("no [")

        items = []
        pos = bracket_start + 1
        depth = 0
        item_start = -1
        for i, ch in enumerate(content[pos:], pos):
            if ch == "{":
                if depth == 0:
                    item_start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and item_start != -1:
                    item_str = content[item_start : i + 1]
                    try:
                        obj = json.loads(item_str)
                        items.append(obj)
                    except json.JSONDecodeError:
                        pass
                    item_start = -1

        if items:
            logger.info(f"截断修复：从截断JSON中提取到 {len(items)} 个完整条目")
            return {
                "date": today,
                "top20": items,
                "analysis_summary": f"（JSON被截断，已恢复{len(items)}个条目）",
            }
    except Exception as e:
        logger.warning(f"截断修复失败: {e}")

    logger.warning("JSON解析完全失败，降级为 raw_response")
    return {
        "date": today,
        "top20": [],
        "raw_response": content,
        "parse_error": "JSON解析失败，请查看 raw_response",
    }


def run_screener_agent(trigger_result: dict) -> dict:
    """
    运行精筛Agent：
    1. 从trigger结果提取企业列表
    2. 收集每家企业量化数据
    3. 调用LLM进行6维度评分（含成本传导判断）
    4. 返回Top 20结果
    """
    logger.info("=== 精筛Agent 启动 (v1.1) ===")
    today = datetime.now().strftime("%Y-%m-%d")

    if not trigger_result.get("has_triggers"):
        logger.info("无触发信息，精筛Agent跳过")
        return {
            "date": today,
            "skipped": True,
            "reason": "触发Agent未发现触发信息",
            "top20": [],
        }

    # Step 1: 提取企业列表
    companies = _extract_companies_from_triggers(trigger_result)
    logger.info(f"提取到 {len(companies)} 家企业待精筛")

    # Step 2: 收集量化数据（有stock_code的才采集）
    company_data_list = []
    for company in companies:
        if company.get("code"):
            logger.info(f"采集数据: {company['name']} ({company['code']})")
            data = _collect_company_data(company["name"], company["code"])
            data["trigger_type"] = company.get("trigger_type", "")
            data["industry"] = company.get("industry", "")
            company_data_list.append(data)
        else:
            company_data_list.append(company)

    # Step 3 & 4: 分两批调用LLM（Top1~10 + Top11~20），规避 8192 token 输出上限
    trigger_summary = json.dumps(trigger_result, ensure_ascii=False, indent=2)
    company_data_text = json.dumps(company_data_list, ensure_ascii=False, indent=2)
    logger.debug("【精筛输入 - 所有企业量化数据】\n" + company_data_text)
    try:
        from tools.db import db as _db
        _content = _db.get_active_prompt("screener", "system_prompt")
    except Exception:
        _content = None
    _screener_prompt = _content if _content else SCREENER_SYSTEM_PROMPT

    llm = build_llm()

    def _call_batch(rank_range: str, batch_label: str) -> list[dict]:
        human_content = f"""今日日期：{today}

【触发Agent输出（初筛结果）】
{trigger_summary}

【各企业量化数据】
{company_data_text}

请对以上企业进行6维度评分，本次只输出排名 {rank_range} 的企业，严格按照JSON格式。
注意：
- 对于没有股票代码的企业，请根据你的知识推断其股票代码和基本情况进行评分。
- 只输出 JSON，不要输出多余文字。
- 每个维度理由控制在15字以内，推荐理由控制在60字以内。
- ⚠️ 特别注意D2维度：原材料/能源涨价时，下游制造企业是成本承压方，D2评0分。"""

        logger.debug(f"【LLM 输入 - {batch_label} Human Message】\n" + human_content)
        messages = [
            SystemMessage(content=_screener_prompt),
            HumanMessage(content=human_content),
        ]
        resp = llm.invoke(messages)
        logger.debug(f"【LLM 输出 - {batch_label} 原始响应】\n" + resp.content)
        batch_result = _parse_screener_json(resp.content, today)
        items = batch_result.get("top20", [])
        for item in items:
            scores = item.get("scores", {})
            total = item.get("total_score", sum(v.get("score", 0) for v in scores.values()))
            logger.info(
                f"  [{batch_label}] #{item.get('rank', '?')} {item.get('name', '')}({item.get('code', '')}) "
                f"总分={total} 触发={item.get('trigger_reason', '')[:30]}"
            )
        return items

    # 从提示词中解析 Top N，默认 20
    import re as _re
    _top_match = _re.search(r'[Tt]op\s*(\d+)', _screener_prompt)
    top_n = int(_top_match.group(1)) if _top_match else 20
    batch_size = 10
    batches_needed = (top_n + batch_size - 1) // batch_size
    logger.info(f"提示词解析 Top N={top_n}，将分 {batches_needed} 批调用LLM")

    all_raw_batches = []
    for i in range(batches_needed):
        start = i * batch_size + 1
        end = min((i + 1) * batch_size, top_n)
        batch_label = f"第{i+1}批"
        rank_range = f"第{start}名到第{end}名（Top {start}~{end}）"
        logger.info(f"调用LLM精筛评分（{batch_label}：Top {start}~{end}）...")
        batch = _call_batch(rank_range, batch_label)
        logger.info(f"{batch_label}完成，得到 {len(batch)} 条")
        all_raw_batches.append(batch)

    # 按 stock_code 去重，保留先出现（排名更靠前）的条目
    seen_codes = set()
    deduped = []
    for batch in all_raw_batches:
        for item in batch:
            code = item.get("code", "")
            if code and code not in seen_codes:
                seen_codes.add(code)
                deduped.append(item)
    all_items = deduped
    batch_summary = "+".join(str(len(b)) for b in all_raw_batches)
    result = {
        "date": today,
        "top20": all_items,
        "analysis_summary": f"共输出 {len(all_items)} 家企业（{batch_summary}，去重后{len(all_items)}）",
    }

    result["date"] = today
    result["companies_analyzed"] = len(companies)

    # 保存精筛结果到 DB（v1.2 新增）
    try:
        from tools.db import db
        db.save_screener(today, result.get("top20", []))
        logger.debug(f"精筛结果已写入 DB：{len(result.get('top20', []))} 条")
    except Exception as e:
        logger.warning(f"DB save_screener 失败（不影响主流程）: {e}")

    logger.info(f"精筛Agent完成：Top {len(result.get('top20', []))} 企业输出")
    logger.debug(
        "【精筛Agent 最终输出】\n" + json.dumps(result, ensure_ascii=False, indent=2)
    )
    return result
