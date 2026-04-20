"""Finalize node: state → Markdown report file."""
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from schemas.skeptic import SkepticFinding
from schemas.state import AgentState

_OUTPUT_DIR = Path(__file__).parent.parent / "outputs" / "runs"


_LEVEL_LABEL = {"recommend": "推荐", "watch": "观察", "skip": "不推荐"}


def _level_display(level: str) -> str:
    return f"{_LEVEL_LABEL.get(level, level)}（{level}）"


def _findings_for(findings: List[SkepticFinding], code: str) -> List[SkepticFinding]:
    return [f for f in findings if f.stock_code == code]


def _render(state: AgentState) -> str:
    run_ts = state.get("run_started_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    trigger = state.get("trigger_summary", {})
    report = state.get("research_report")
    screener = state.get("screener_result")
    skeptic = state.get("skeptic_result")
    last_decision = state.get("last_decision")
    steps = state.get("completed_steps", [])

    counts = {"research": 0, "screener": 0, "skeptic": 0, "supervisor": 0}
    for s in steps:
        n = s.get("node")
        if n in counts:
            counts[n] += 1

    lines: List[str] = []
    lines.append(f"# 今日推荐 — {run_ts.split(' ')[0] if ' ' in run_ts else run_ts}")
    lines.append("")
    lines.append(f"> 运行时间：{run_ts}")
    lines.append(f"> Trigger 数：1")
    lines.append(f"> LangSmith Trace：见 LANGSMITH_PROJECT={os.getenv('LANGSMITH_PROJECT', '')}")
    lines.append("")
    lines.append("## 触发信号概览")
    lines.append("")
    lines.append(f"### 1. {trigger.get('headline', '(无 headline)')}")
    lines.append("")
    lines.append(f"- **行业**：{trigger.get('industry', '-')}")
    lines.append(f"- **类型**：{trigger.get('type', '-')}")
    lines.append(f"- **强度**：{trigger.get('strength', '-')}")
    lines.append(f"- **来源**：{trigger.get('source', '-')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 推荐列表（按 Screener 总分降序）")
    lines.append("")

    if screener and screener.stocks:
        lines.append("| 代码 | 名称 | 总分 | 等级 | 关联触发 |")
        lines.append("|---|---|---|---|---|")
        for s in screener.stocks:
            lines.append(f"| {s.code} | {s.name} | {s.total_score} | {_level_display(s.recommendation_level)} | {s.trigger_ref} |")
    else:
        lines.append("_无 Screener 结果_")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 每只股票分析链路")
    lines.append("")

    candidates_by_code: Dict[str, Any] = {}
    if report:
        candidates_by_code = {c.code: c for c in report.candidates}

    findings = skeptic.findings if skeptic else []

    if screener:
        for s in screener.stocks:
            lines.append(f"### {s.name} {s.code} — 总分 {s.total_score} [{_level_display(s.recommendation_level)}]")
            lines.append("")
            lines.append("#### ① 触发来源")
            lines.append("")
            lines.append(f"{s.trigger_ref}")
            lines.append("")
            lines.append("#### ② Research Agent 调研摘要")
            lines.append("")
            entry = candidates_by_code.get(s.code)
            if entry:
                lines.append(f"- **行业龙头**：{entry.leadership or '-'}")
                lines.append(f"- **股东结构**：{entry.holder_structure or '-'}")
                lines.append(f"- **财务**：{entry.financial_summary or '-'}")
                lines.append(f"- **技术面**：{entry.technical_summary or '-'}")
                lines.append(f"- **产品涨价受益**：{entry.price_benefit or '-'}")
                if entry.data_gaps:
                    lines.append("")
                    lines.append(f"> ⚠️ 数据缺口：{', '.join(entry.data_gaps)}")
            else:
                lines.append("_无 Research 数据_")
            lines.append("")
            lines.append("#### ③ Screener 评分明细")
            lines.append("")
            lines.append("| 条件 | 权重 | 满足度 | 得分 | 推理 |")
            lines.append("|---|---|---|---|---|")
            for cs in s.condition_scores:
                reasoning = cs.reasoning.replace("\n", " ").replace("|", "/")
                lines.append(
                    f"| {cs.condition_id} {cs.condition_name} | {cs.weight} | {cs.satisfaction} | {cs.weighted_score} | {reasoning} |"
                )
            lines.append("")
            lines.append("#### ④ Skeptic 质疑")
            lines.append("")
            stock_findings = _findings_for(findings, s.code)
            if stock_findings:
                for f in stock_findings:
                    lines.append(f"- **[{f.finding_type}]** {f.content}")
            else:
                lines.append("_无 Skeptic 对本股票的质疑_")
            lines.append("")
            lines.append("---")
            lines.append("")

    # Supervisor 综合判断：整份报告级别，而非 per-股票（避免每股重复同一段）
    notes = last_decision.notes if last_decision and last_decision.notes else ""
    lines.append("## Supervisor 综合判断")
    lines.append("")
    if notes:
        lines.append(f"> {notes}")
    else:
        lines.append("> _Supervisor 在 finalize 决策中未填 notes 字段（可在 config/prompts/supervisor.md 加强要求）_")
    lines.append("")

    lines.append("## 本次运行元信息")
    lines.append("")
    lines.append(f"- Supervisor 决策轮次：{counts['supervisor']}")
    lines.append(f"- 子 Agent 调用次数：Research × {counts['research']}，Screener × {counts['screener']}，Skeptic × {counts['skeptic']}")
    lines.append(f"- LangSmith Project：{os.getenv('LANGSMITH_PROJECT', '(未配置)')}")
    lines.append("")
    return "\n".join(lines)


def finalize_node(state: AgentState) -> Dict[str, Any]:
    """Phase 3：不再写 Markdown 文件；DB 为唯一事实源。

    若需查看报告：python scripts/show_run.py [run_id]
    """
    completed_steps = list(state.get("completed_steps", []))
    completed_steps.append({
        "node": "finalize",
        "run_id": state.get("run_id"),
    })
    return {"completed_steps": completed_steps}


def render_from_state(state: AgentState) -> str:
    """独立渲染函数（供 scripts/show_run.py 从 DB 重建 state 后调用）。"""
    return _render(state)
