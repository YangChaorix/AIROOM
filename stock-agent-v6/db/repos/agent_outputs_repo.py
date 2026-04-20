"""agent_outputs 通用 Repository（档位 A 核心）——所有 agent 的顶层输出都用这个。

支持任意 agent_name，无需为新 agent 加表/改 schema。
"""
import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from db.models import AgentOutput


def log(sess: Session, run_id: int, agent_name: str, sequence: int,
        summary: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None) -> int:
    """落一条 agent 顶层输出；返回新行 id 供明细表 FK 使用。

    Args:
        sess: 活跃 session（调用方负责 commit）
        run_id: 所属 run
        agent_name: 'supervisor' / 'research' / 'screener' / 'skeptic' / 未来任意
        sequence: 本 run 内该 agent 的第几次激活（Supervisor 1-4；其他通常 1）
        summary: 通用文字摘要（reasoning / comparison_summary / ...）
        payload: 各 agent 专属结构化数据（会 json.dumps 存入 payload_json）
        metrics: 运行指标（latency_ms, tokens 等）
    """
    row = AgentOutput(
        run_id=run_id,
        agent_name=agent_name,
        sequence=sequence,
        status=status,
        summary=summary,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str) if payload else None,
        metrics_json=json.dumps(metrics, ensure_ascii=False, default=str) if metrics else None,
        metadata_json=json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None,
    )
    sess.add(row)
    sess.flush()
    ao_id = row.id
    sess.commit()
    return ao_id
