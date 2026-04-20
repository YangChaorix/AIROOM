"""Research 落盘：stock_data_entries + tool_calls（agent_outputs 顶层由 agent_outputs_repo 处理）。"""
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from db.models import StockDataEntry, ToolCall
from schemas.research import ResearchReport


def bulk_insert_stock_data_entries(sess: Session, agent_output_id: int,
                                   report: ResearchReport) -> Dict[str, int]:
    """写 stock_data_entries；返回 {code: sde_id} 映射给 Screener 外键用。"""
    code_to_id: Dict[str, int] = {}
    for c in report.candidates:
        row = StockDataEntry(
            agent_output_id=agent_output_id,
            code=c.code,
            name=c.name,
            industry=c.industry,
            leadership=c.leadership,
            holder_structure=c.holder_structure,
            financial_summary=c.financial_summary,
            technical_summary=c.technical_summary,
            price_benefit=c.price_benefit,
            data_gaps_json=json.dumps(c.data_gaps, ensure_ascii=False) if c.data_gaps else None,
            sources_json=json.dumps(c.sources, ensure_ascii=False) if c.sources else None,
        )
        sess.add(row)
        sess.flush()
        code_to_id[c.code] = row.id
    sess.commit()
    return code_to_id


def bulk_insert_tool_calls(sess: Session, agent_output_id: int, intermediate_steps) -> int:
    """把 AgentExecutor intermediate_steps 批量落盘。返回条目数。"""
    count = 0
    for seq, step in enumerate(intermediate_steps, start=1):
        action = step[0]
        observation = step[1]
        tool_name = getattr(action, "tool", None) or "?"
        args = getattr(action, "tool_input", None)
        args_json = json.dumps(args, ensure_ascii=False, default=str) if args else "{}"
        stock_code = None
        if isinstance(args, dict) and args.get("code"):
            stock_code = str(args["code"])
        preview = str(observation)[:500] if observation else None
        row = ToolCall(
            agent_output_id=agent_output_id,
            sequence=seq,
            tool_name=tool_name,
            args_json=args_json,
            stock_code=stock_code,
            result_preview=preview,
            latency_ms=None,  # 暂无，可扩展
            error=None,
        )
        sess.add(row)
        count += 1
    sess.commit()
    return count
