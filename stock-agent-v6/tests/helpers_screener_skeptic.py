"""Screener / Skeptic 的假 _call_llm，用于结构测试中替换真 LLM。

返回的字符串必须能被各 agent 的 JSON 解析逻辑接受（即符合对应 Pydantic schema）。
"""
import json
import re

from schemas.research import ResearchReport


def _extract_research_from_prompt(prompt: str):
    """从 Screener prompt 里把 research_report_json 段反序列化回 ResearchReport。"""
    # 定位 "### Research Agent 提供的候选股票数据" 后的 ```json ... ```
    m = re.search(r"候选股票数据\s*```json\s*(.*?)```", prompt, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        return ResearchReport(**data)
    except Exception:
        return None


def _extract_scoreable_from_prompt(prompt: str):
    m = re.search(r"用户选股条件.*?```json\s*(.*?)```", prompt, re.DOTALL)
    if not m:
        return []
    try:
        return json.loads(m.group(1))
    except Exception:
        return []


def fake_screener_call_llm(prompt: str) -> str:
    """构造一个"每条件都给 0.5"的打分结果，满足 ScreenerResult schema。"""
    report = _extract_research_from_prompt(prompt)
    scoreable = _extract_scoreable_from_prompt(prompt)
    threshold_match = re.search(r"推荐分数门槛\s*\n\s*([0-9.]+)", prompt)
    threshold = float(threshold_match.group(1)) if threshold_match else 0.65

    stocks_payload = []
    if report:
        for c in report.candidates:
            condition_scores = []
            total = 0.0
            for cond in scoreable:
                satisfaction = 0.5
                weight = float(cond.get("weight", 0))
                weighted = satisfaction * weight
                total += weighted
                condition_scores.append({
                    "condition_id": cond["id"],
                    "condition_name": cond["name"],
                    "satisfaction": satisfaction,
                    "weight": weight,
                    "weighted_score": round(weighted, 4),
                    "reasoning": f"[MOCK] 测试占位推理，满足度默认 0.5，权重 {weight}（≥15 字符）",
                })
            level = "recommend" if total >= threshold else ("watch" if total >= 0.5 else "skip")
            stocks_payload.append({
                "code": c.code,
                "name": c.name,
                "total_score": round(total, 4),
                "recommendation_level": level,
                "condition_scores": condition_scores,
                "data_gaps": [],
                "trigger_ref": report.trigger_ref,
            })

    if not stocks_payload:
        stocks_payload = [{
            "code": "000000",
            "name": "[MOCK] 占位",
            "total_score": 0.5,
            "recommendation_level": "watch",
            "condition_scores": [{
                "condition_id": "C?",
                "condition_name": "占位",
                "satisfaction": 0.5,
                "weight": 1.0,
                "weighted_score": 0.5,
                "reasoning": "[MOCK] 无可用 Research 数据，结构占位（≥15 字符）",
            }],
            "data_gaps": [],
            "trigger_ref": "T-MOCK",
        }]

    return json.dumps({"stocks": stocks_payload, "threshold_used": threshold}, ensure_ascii=False)


def fake_skeptic_call_llm(prompt: str) -> str:
    """构造一个至少含 1 个 logic_risk + 1 个 data_gap 的 mock。"""
    # 从 prompt 里抽 TOP5 的股票代码
    codes = re.findall(r'"code":\s*"(\d{6})"', prompt)
    top5 = codes[:5] if codes else ["000000"]
    findings = []
    for code in top5:
        findings.append({
            "stock_code": code,
            "finding_type": "logic_risk",
            "content": f"[MOCK] {code} 的推理风险占位文本，用于测试（≥20 字符）",
        })
        findings.append({
            "stock_code": code,
            "finding_type": "data_gap",
            "content": f"[MOCK] {code} 的数据缺口占位文本，用于测试（≥20 字符）",
        })
    return json.dumps({"findings": findings, "covered_stocks": top5}, ensure_ascii=False)
