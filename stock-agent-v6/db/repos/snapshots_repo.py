"""AkShare 数据快照的 Repository（跨运行复用，减少重复网络调用）。

三张快照表通用模式：按 (code, as_of) 去重；命中返回缓存，未命中由工具层调 AkShare + 入库。
"""
import json
from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import FinancialSnapshot, HolderSnapshot, TechnicalSnapshot


def _today() -> date:
    return datetime.utcnow().date()


# ── financial ──

def get_financial(sess: Session, code: str, as_of: date) -> Optional[Dict[str, Any]]:
    row = sess.scalar(
        select(FinancialSnapshot).where(
            FinancialSnapshot.code == code,
            FinancialSnapshot.as_of == as_of,
        )
    )
    if not row:
        return None
    try:
        return json.loads(row.raw_json)
    except Exception:
        return None


def upsert_financial(sess: Session, code: str, as_of: date, payload: Dict[str, Any]) -> None:
    existing = sess.scalar(
        select(FinancialSnapshot).where(
            FinancialSnapshot.code == code,
            FinancialSnapshot.as_of == as_of,
        )
    )
    data_str = json.dumps(payload, ensure_ascii=False, default=str)
    if existing:
        existing.raw_json = data_str
        existing.financial_summary = payload.get("financial_summary")
        existing.latest_period = payload.get("latest_period")
        existing.yoy_period = payload.get("yoy_period")
    else:
        sess.add(FinancialSnapshot(
            code=code, as_of=as_of, raw_json=data_str,
            source=payload.get("source", "sina"),
            latest_period=payload.get("latest_period"),
            yoy_period=payload.get("yoy_period"),
            financial_summary=payload.get("financial_summary"),
        ))
    sess.commit()


# ── holder ──

def get_holder(sess: Session, code: str, as_of: date) -> Optional[Dict[str, Any]]:
    row = sess.scalar(
        select(HolderSnapshot).where(
            HolderSnapshot.code == code,
            HolderSnapshot.as_of == as_of,
        )
    )
    if not row:
        return None
    try:
        return json.loads(row.raw_json)
    except Exception:
        return None


def upsert_holder(sess: Session, code: str, as_of: date, payload: Dict[str, Any]) -> None:
    existing = sess.scalar(
        select(HolderSnapshot).where(
            HolderSnapshot.code == code,
            HolderSnapshot.as_of == as_of,
        )
    )
    data_str = json.dumps(payload, ensure_ascii=False, default=str)
    if existing:
        existing.raw_json = data_str
        existing.smart_money_pct = payload.get("smart_money_pct")
        existing.state_pct = payload.get("state_pct")
        existing.foreign_pct = payload.get("foreign_pct")
        existing.holder_structure = payload.get("holder_structure")
    else:
        sess.add(HolderSnapshot(
            code=code, as_of=as_of, raw_json=data_str,
            source=payload.get("source", "eastmoney"),
            smart_money_pct=payload.get("smart_money_pct"),
            state_pct=payload.get("state_pct"),
            foreign_pct=payload.get("foreign_pct"),
            holder_structure=payload.get("holder_structure"),
        ))
    sess.commit()


# ── technical ──

def get_technical(sess: Session, code: str, as_of: date) -> Optional[Dict[str, Any]]:
    row = sess.scalar(
        select(TechnicalSnapshot).where(
            TechnicalSnapshot.code == code,
            TechnicalSnapshot.as_of == as_of,
        )
    )
    if not row:
        return None
    try:
        return json.loads(row.raw_json)
    except Exception:
        return None


def upsert_technical(sess: Session, code: str, as_of: date, payload: Dict[str, Any]) -> None:
    existing = sess.scalar(
        select(TechnicalSnapshot).where(
            TechnicalSnapshot.code == code,
            TechnicalSnapshot.as_of == as_of,
        )
    )
    data_str = json.dumps(payload, ensure_ascii=False, default=str)
    if existing:
        existing.raw_json = data_str
        existing.close = payload.get("close")
        existing.ma20 = payload.get("ma20")
        existing.volume_ratio = payload.get("volume_ratio")
        existing.macd_signal = payload.get("macd_signal")
        existing.technical_summary = payload.get("technical_summary")
    else:
        sess.add(TechnicalSnapshot(
            code=code, as_of=as_of, raw_json=data_str,
            source=payload.get("source", "sina"),
            close=payload.get("close"),
            ma20=payload.get("ma20"),
            volume_ratio=payload.get("volume_ratio"),
            macd_signal=payload.get("macd_signal"),
            technical_summary=payload.get("technical_summary"),
        ))
    sess.commit()
