"""
Agent 3 — 每日收盘复盘（15:35 运行）

任务一（Python规则）：
  - 获取全市场涨幅/跌幅前50
  - 读取昨日推送记录，对比当日涨跌，计算命中率

任务二（LLM×1）：
  - 输入：涨幅前50 + 推送验证结果 + 是否周五
  - 输出：市场总结 / 热点板块 / 推送命中率 / 明日关注 / 周五教训
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

import akshare as ak
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config.settings import settings


REVIEW_SYSTEM_PROMPT = """你是A股专业复盘分析师，擅长从每日市场数据中提炼规律和教训。

你的任务是完成今日收盘复盘，输出以下内容：

1. **市场总结**：今日大盘走势、整体情绪（乐观/中性/悲观）
2. **热点板块**：今日涨幅最大的板块及驱动原因
3. **推送命中率**：昨日/今日推送股票的表现验证
4. **明日关注**：基于今日事件，明日需关注的方向
5. **经验教训**（如果是周五，额外输出本周复盘）

请以JSON格式输出：
{
  "market_sentiment": "乐观/中性/悲观",
  "market_summary": "<100字内市场总结>",
  "hot_sectors": [
    {"sector": "板块名", "reason": "驱动原因", "top_stocks": ["股票名1", "股票名2"]}
  ],
  "push_verification": {
    "hit_count": <命中数量>,
    "total_pushed": <推送总数>,
    "hit_rate_pct": <命中率百分比>,
    "hit_stocks": ["命中股票1", "命中股票2"],
    "miss_stocks": ["未中股票1"],
    "analysis": "<命中率分析，50字内>"
  },
  "tomorrow_focus": ["关注方向1", "关注方向2"],
  "lessons_learned": "<今日经验教训，50字内>",
  "weekly_summary": "<仅周五输出：本周推送准确率统计和复盘，100字内>",
  "is_friday_review": true/false
}
"""


def _get_market_movers() -> dict[str, Any]:
    """
    获取全市场涨幅/跌幅前50

    Returns:
        {
            "top_gainers": list[dict],   # 涨幅前50
            "top_losers": list[dict],    # 跌幅前50
            "date": str,
        }
    """
    try:
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return {"top_gainers": [], "top_losers": [], "date": datetime.now().strftime("%Y-%m-%d")}

        # 涨幅前50
        gainers_df = df.sort_values("涨跌幅", ascending=False).head(50)
        gainers = []
        for _, row in gainers_df.iterrows():
            gainers.append({
                "代码": str(row.get("代码", "")).zfill(6),
                "名称": str(row.get("名称", "")),
                "涨跌幅": float(row.get("涨跌幅", 0) or 0),
                "最新价": float(row.get("最新价", 0) or 0),
                "成交额": float(row.get("成交额", 0) or 0),
            })

        # 跌幅前50
        losers_df = df.sort_values("涨跌幅", ascending=True).head(50)
        losers = []
        for _, row in losers_df.iterrows():
            losers.append({
                "代码": str(row.get("代码", "")).zfill(6),
                "名称": str(row.get("名称", "")),
                "涨跌幅": float(row.get("涨跌幅", 0) or 0),
            })

        return {
            "top_gainers": gainers,
            "top_losers": losers,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
    except Exception as e:
        return {
            "top_gainers": [],
            "top_losers": [],
            "date": datetime.now().strftime("%Y-%m-%d"),
            "error": str(e),
        }


def _load_push_record(target_date: Optional[str] = None) -> Optional[dict[str, Any]]:
    """
    读取指定日期的推送记录

    Args:
        target_date: 日期字符串 YYYY-MM-DD，默认为今天

    Returns:
        推送记录字典，如不存在则返回 None
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "daily_push")
    file_path = os.path.join(data_dir, f"{target_date}.json")

    if not os.path.exists(file_path):
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _verify_push_against_market(
    push_record: Optional[dict[str, Any]],
    market_data: dict[str, Any],
) -> dict[str, Any]:
    """
    对比推送记录与当日市场表现，计算命中率

    命中定义：推送股票当日涨幅 > 2%

    Returns:
        验证结果字典
    """
    if not push_record or not push_record.get("top20"):
        return {
            "hit_count": 0,
            "total_pushed": 0,
            "hit_rate_pct": 0.0,
            "hit_stocks": [],
            "miss_stocks": [],
            "details": [],
        }

    pushed_stocks = push_record["top20"]
    gainers = market_data.get("top_gainers", [])
    gainer_codes = {g["代码"]: g["涨跌幅"] for g in gainers}
    # 也从全市场行情中获取所有股票今日涨跌幅（如需精确匹配）
    # 此处简化：以涨幅前50为"命中"参考
    all_codes_pct: dict[str, float] = {g["代码"]: g["涨跌幅"] for g in gainers}

    hit_stocks = []
    miss_stocks = []
    details = []

    for stock in pushed_stocks:
        code = stock.get("代码", "")
        name = stock.get("名称", "")
        pct = all_codes_pct.get(code)
        if pct is None:
            # 未在涨幅前50中，认为未命中
            miss_stocks.append(name)
            details.append({"代码": code, "名称": name, "涨跌幅": "未在涨幅前50", "命中": False})
        elif pct > 2.0:
            hit_stocks.append(name)
            details.append({"代码": code, "名称": name, "涨跌幅": pct, "命中": True})
        else:
            miss_stocks.append(name)
            details.append({"代码": code, "名称": name, "涨跌幅": pct, "命中": False})

    total = len(pushed_stocks)
    hit_count = len(hit_stocks)
    hit_rate = round(hit_count / total * 100, 1) if total > 0 else 0.0

    return {
        "hit_count": hit_count,
        "total_pushed": total,
        "hit_rate_pct": hit_rate,
        "hit_stocks": hit_stocks,
        "miss_stocks": miss_stocks,
        "details": details,
        "push_date": push_record.get("date", ""),
    }


def _load_weekly_push_records() -> list[dict[str, Any]]:
    """加载本周（最近5个交易日）的推送记录"""
    records = []
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data", "daily_push")
    if not os.path.exists(data_dir):
        return records

    today = datetime.now().date()
    for delta in range(7):  # 往前看7天，取最多5条
        check_date = today - timedelta(days=delta)
        file_path = os.path.join(data_dir, f"{check_date.isoformat()}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    records.append(json.load(f))
                if len(records) >= 5:
                    break
            except Exception:
                pass
    return records


def _save_review_result(review_result: dict[str, Any]) -> None:
    """保存复盘结果到 data/review_history/{date}.json"""
    date_str = review_result.get("date", datetime.now().strftime("%Y-%m-%d"))
    save_dir = os.path.join(os.path.dirname(__file__), "..", "data", "review_history")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, f"{date_str}.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(review_result, f, ensure_ascii=False, indent=2, default=str)
    print(f"  → 复盘记录已保存：{save_path}")


async def run_review_agent(push_date: Optional[str] = None) -> dict[str, Any]:
    """
    执行 Agent 3：每日收盘复盘

    Args:
        push_date: 要验证的推送日期（默认今天）

    Returns:
        复盘结果字典
    """
    print("\n[Agent 3] 开始收盘复盘...")
    today_str = datetime.now().strftime("%Y-%m-%d")
    is_friday = datetime.now().weekday() == 4  # 0=周一, 4=周五

    # ── 任务一：Python规则 ──────────────────────────────────
    print("  [Step 1] 获取全市场行情（涨跌幅排行）...")
    market_data = _get_market_movers()
    top5_preview = ["{0}({1:.1f}%)".format(g["名称"], g["涨跌幅"]) for g in market_data["top_gainers"][:5]]
    print(f"  → 涨幅前5：{top5_preview}")

    print("  [Step 2] 读取推送记录并验证...")
    push_record = _load_push_record(push_date or today_str)
    if push_record:
        print(f"  → 找到推送记录（{push_record.get('date')}），共推送 {len(push_record.get('top20', []))} 只")
    else:
        print(f"  → 未找到今日推送记录（{push_date or today_str}）")

    verification = _verify_push_against_market(push_record, market_data)
    print(f"  → 命中率：{verification['hit_count']}/{verification['total_pushed']} = {verification['hit_rate_pct']}%")

    # ── 任务二：LLM 分析 ────────────────────────────────────
    print("  [Step 3] LLM 生成复盘报告...")

    # 构建涨幅前20的文本摘要
    gainers_text = "\n".join(
        f"{i+1}. {g['名称']}({g['代码']}) +{g['涨跌幅']:.1f}%"
        for i, g in enumerate(market_data["top_gainers"][:20])
    )

    # 验证摘要
    push_summary = ""
    if push_record:
        hit_names = "、".join(verification["hit_stocks"][:5]) or "无"
        miss_names = "、".join(verification["miss_stocks"][:5]) or "无"
        push_summary = (
            f"\n推送验证：推送{verification['total_pushed']}只，命中{verification['hit_count']}只"
            f"（命中率{verification['hit_rate_pct']}%）\n"
            f"命中股票：{hit_names}\n未命中代表：{miss_names}"
        )

    # 周五额外加载本周数据
    weekly_text = ""
    if is_friday:
        weekly_records = _load_weekly_push_records()
        if weekly_records:
            total_pushed_week = sum(len(r.get("top20", [])) for r in weekly_records)
            weekly_text = f"\n\n本周共推送 {total_pushed_week} 只股票（{len(weekly_records)} 个交易日），请输出周度复盘。"

    user_message = f"""今日日期：{today_str}（{'周五，请输出周度复盘' if is_friday else '非周五'}）

**今日A股涨幅前20名：**
{gainers_text}
{push_summary}
{weekly_text}

请完成今日收盘复盘分析，输出JSON格式结果。"""

    llm = ChatOpenAI(
        model=settings.deepseek.model_name,
        api_key=settings.deepseek.api_key,
        base_url=settings.deepseek.base_url,
        temperature=0.3,
        max_tokens=1500,
    )

    response = await llm.ainvoke([
        SystemMessage(content=REVIEW_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ])

    try:
        json_match = re.search(r'\{[\s\S]*\}', response.content)
        if json_match:
            llm_review = json.loads(json_match.group())
        else:
            llm_review = {"market_summary": response.content[:200]}
    except json.JSONDecodeError:
        llm_review = {"market_summary": response.content[:200]}

    # 汇总结果
    review_result = {
        "date": today_str,
        "is_friday": is_friday,
        "market_data": {
            "top_gainers_count": len(market_data["top_gainers"]),
            "top_gainers_preview": [
                f"{g['名称']}+{g['涨跌幅']:.1f}%" for g in market_data["top_gainers"][:10]
            ],
        },
        "push_verification": verification,
        "llm_review": llm_review,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 打印摘要
    print(f"\n  ── 复盘摘要 ──")
    print(f"  市场情绪：{llm_review.get('market_sentiment', 'N/A')}")
    print(f"  市场总结：{llm_review.get('market_summary', '')[:80]}")
    print(f"  命中率：{verification['hit_rate_pct']}%")
    tomorrow = llm_review.get("tomorrow_focus", [])
    if tomorrow:
        print(f"  明日关注：{', '.join(tomorrow[:3])}")

    # 保存复盘记录
    _save_review_result(review_result)

    return review_result
