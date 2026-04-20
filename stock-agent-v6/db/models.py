"""SQLAlchemy ORM models — Phase 3 数据持久化。

14 张物理表；2 张 SQL View 在 Alembic migration 中手写 CREATE VIEW。

字段含义见 docs/PHASE3_DB_PLAN.md §3；此文件只承担 Python 映射。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Float,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _now_utc() -> datetime:
    return datetime.utcnow()


# ─────────────────────────────────────────────────────────────
# 表 1: users
# ─────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    recommendation_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)
    trading_style: Mapped[Optional[str]] = mapped_column(String)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc, onupdate=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 2: conditions
# ─────────────────────────────────────────────────────────────
class Condition(Base):
    __tablename__ = "conditions"
    __table_args__ = (
        UniqueConstraint("user_id", "condition_id", name="uq_conditions_user_condition"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.user_id"), nullable=False)
    condition_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    layer: Mapped[str] = mapped_column(String, nullable=False)  # trigger / screener / entry
    description: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Optional[float]] = mapped_column(Float)
    keywords_json: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc, onupdate=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 3: news_items（去重键 content_hash = SHA256(title+source)，不含时间）
# ─────────────────────────────────────────────────────────────
class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (
        Index("ix_news_source_pub", "source", "published_at"),
        Index("ix_news_consumed", "consumed_by_trigger_id"),
        # 未消费的 news 是 Trigger Agent 的候选池，按 created_at 倒序查
        Index("ix_news_pending", "consumed_by_trigger_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    # ── Phase 6 新增：消费标记（一条 news 最多关联 1 个 trigger）──
    consumed_by_trigger_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("triggers.id"))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ─────────────────────────────────────────────────────────────
# 表 5: runs（先于 triggers 定义，triggers 引用 run_id）
# ─────────────────────────────────────────────────────────────
class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.user_id"))
    trigger_key: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error: Mapped[Optional[str]] = mapped_column(Text)
    langsmith_project: Mapped[Optional[str]] = mapped_column(String)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc, onupdate=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 4: triggers
# ─────────────────────────────────────────────────────────────
class Trigger(Base):
    __tablename__ = "triggers"
    __table_args__ = (
        Index("ix_triggers_dedup", "industry", "type", "mode", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # run_id：遗留字段，语义是"产生该 trigger 的 run"（如果有的话）；Phase 6 之后
    # 主要用 consumed_by_run_id 表示"消费该 trigger 的 run"
    run_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("runs.id"))
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    industry: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    strength: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)  # live / fixture / individual_stock / agent_generated
    source_news_ids: Mapped[Optional[str]] = mapped_column(Text)  # JSON array
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)  # Phase 4: focus_codes/focus_primary/peer_names
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    # ── Phase 6 新增：事件队列字段 ──
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    # status: pending / processing / completed / failed / skipped
    consumed_by_run_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("runs.id"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # priority 1-10，Trigger Agent 打分后写入；main.py 消费时按 priority DESC + created_at ASC
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # ── Phase 6.1：主题级去重计数（(industry+type+日期) 同主题再次命中只累加，不新建）──
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ─────────────────────────────────────────────────────────────
# 表 6: agent_outputs（★ 档位 A 核心 —— 4 种 agent 合并的通用表）
# ─────────────────────────────────────────────────────────────
class AgentOutput(Base):
    __tablename__ = "agent_outputs"
    __table_args__ = (
        UniqueConstraint("run_id", "agent_name", "sequence", name="uq_agent_outputs"),
        Index("ix_agent_outputs_name_time", "agent_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String, nullable=False)  # supervisor / research / screener / skeptic / <future>
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)   # Supervisor 1-4；其他 1
    status: Mapped[str] = mapped_column(String, nullable=False, default="success")
    summary: Mapped[Optional[str]] = mapped_column(Text)             # 通用文字摘要（reasoning / comparison_summary / ...）
    payload_json: Mapped[Optional[str]] = mapped_column(Text)        # 各 agent 专属结构化数据
    metrics_json: Mapped[Optional[str]] = mapped_column(Text)        # {latency_ms, tokens, ...}
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 7: stock_data_entries
# ─────────────────────────────────────────────────────────────
class StockDataEntry(Base):
    __tablename__ = "stock_data_entries"
    __table_args__ = (
        UniqueConstraint("agent_output_id", "code", name="uq_sde_agent_code"),
        Index("ix_sde_code_time", "code", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_output_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_outputs.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    industry: Mapped[str] = mapped_column(String, nullable=False)
    leadership: Mapped[Optional[str]] = mapped_column(Text)
    holder_structure: Mapped[Optional[str]] = mapped_column(Text)
    financial_summary: Mapped[Optional[str]] = mapped_column(Text)
    technical_summary: Mapped[Optional[str]] = mapped_column(Text)
    price_benefit: Mapped[Optional[str]] = mapped_column(Text)
    data_gaps_json: Mapped[Optional[str]] = mapped_column(Text)
    sources_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 8: tool_calls
# ─────────────────────────────────────────────────────────────
class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        Index("ix_tc_agent_seq", "agent_output_id", "sequence"),
        Index("ix_tc_code_time", "stock_code", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_output_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_outputs.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    args_json: Mapped[str] = mapped_column(Text, nullable=False)
    stock_code: Mapped[Optional[str]] = mapped_column(String)
    result_preview: Mapped[Optional[str]] = mapped_column(Text)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 9: stock_recommendations（★ 业务摘要核心载体）
# ─────────────────────────────────────────────────────────────
class StockRecommendation(Base):
    __tablename__ = "stock_recommendations"
    __table_args__ = (
        Index("ix_sr_agent_rank", "agent_output_id", "rank"),
        Index("ix_sr_code_time", "code", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_output_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_outputs.id"), nullable=False)
    stock_data_entry_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("stock_data_entries.id"))
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    recommendation_level: Mapped[str] = mapped_column(String, nullable=False)  # recommend / watch / skip
    rank: Mapped[Optional[int]] = mapped_column(Integer)
    # ★ Phase 3 新增业务摘要字段
    recommendation_rationale: Mapped[Optional[str]] = mapped_column(Text)
    key_strengths_json: Mapped[Optional[str]] = mapped_column(Text)
    key_risks_json: Mapped[Optional[str]] = mapped_column(Text)
    data_gaps_json: Mapped[Optional[str]] = mapped_column(Text)
    trigger_ref: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 10: condition_scores
# ─────────────────────────────────────────────────────────────
class ConditionScore(Base):
    __tablename__ = "condition_scores"
    __table_args__ = (
        UniqueConstraint("stock_recommendation_id", "condition_id", name="uq_cs_rec_cond"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stock_recommendation_id: Mapped[int] = mapped_column(Integer, ForeignKey("stock_recommendations.id"), nullable=False)
    condition_id: Mapped[str] = mapped_column(String, nullable=False)
    condition_name: Mapped[str] = mapped_column(String, nullable=False)
    satisfaction: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    weighted_score: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 11: skeptic_findings
# ─────────────────────────────────────────────────────────────
class SkepticFinding(Base):
    __tablename__ = "skeptic_findings"
    __table_args__ = (
        Index("ix_sf_agent_code", "agent_output_id", "stock_code"),
        Index("ix_sf_rec", "stock_recommendation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_output_id: Mapped[int] = mapped_column(Integer, ForeignKey("agent_outputs.id"), nullable=False)
    stock_recommendation_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("stock_recommendations.id"))
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    finding_type: Mapped[str] = mapped_column(String, nullable=False)  # logic_risk / data_gap
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 12-14: AkShare 快照（跨运行复用，唯一键 (code, as_of)）
# ─────────────────────────────────────────────────────────────
class FinancialSnapshot(Base):
    __tablename__ = "financial_snapshots"
    __table_args__ = (UniqueConstraint("code", "as_of", name="uq_fin_code_asof"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    as_of: Mapped[datetime] = mapped_column(Date, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    latest_period: Mapped[Optional[str]] = mapped_column(String)
    yoy_period: Mapped[Optional[str]] = mapped_column(String)
    financial_summary: Mapped[Optional[str]] = mapped_column(Text)
    raw_metrics_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=_now_utc)


class HolderSnapshot(Base):
    __tablename__ = "holder_snapshots"
    __table_args__ = (UniqueConstraint("code", "as_of", name="uq_hold_code_asof"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    as_of: Mapped[datetime] = mapped_column(Date, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    smart_money_pct: Mapped[Optional[float]] = mapped_column(Float)
    state_pct: Mapped[Optional[float]] = mapped_column(Float)
    foreign_pct: Mapped[Optional[float]] = mapped_column(Float)
    holder_structure: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=_now_utc)


class TechnicalSnapshot(Base):
    __tablename__ = "technical_snapshots"
    __table_args__ = (UniqueConstraint("code", "as_of", name="uq_tech_code_asof"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    as_of: Mapped[datetime] = mapped_column(Date, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    close: Mapped[Optional[float]] = mapped_column(Float)
    ma20: Mapped[Optional[float]] = mapped_column(Float)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float)
    macd_signal: Mapped[Optional[str]] = mapped_column(String)
    technical_summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, onupdate=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 16（前端 Phase / F0 新增）：prompt_versions — Prompt 版本化
# ─────────────────────────────────────────────────────────────
class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("agent_name", "version_code", name="uq_prompt_agent_version"),
        Index("ix_prompt_agent_active", "agent_name", "is_active"),
        Index("ix_prompt_created", "agent_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String, nullable=False)  # supervisor/research/screener/skeptic/trigger
    version_code: Mapped[str] = mapped_column(String, nullable=False)  # YYYYMMDD + 4 位当日序号
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    author: Mapped[Optional[str]] = mapped_column(String)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)


# ─────────────────────────────────────────────────────────────
# 表 15（Phase 5 新增）：system_logs — 全局日志（调度器/Agent/工具层都可写入）
# ─────────────────────────────────────────────────────────────
class SystemLog(Base):
    __tablename__ = "system_logs"
    __table_args__ = (
        Index("ix_syslog_level_time", "level", "created_at"),
        Index("ix_syslog_source_time", "source", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String, nullable=False)  # info / warning / error
    source: Mapped[str] = mapped_column(String, nullable=False)  # 如 "scheduler.news_cctv" / "agents.supervisor"
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[Optional[str]] = mapped_column(Text)    # 错误堆栈 / 调用参数 / 额外上下文
    run_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("runs.id"))  # 可选：关联 run
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now_utc)


# ─────────────────────────────────────────────────────────────
# SQL Views (v_recommendation_trace, v_stock_analysis_history)
# 由 Alembic migration 手写 CREATE VIEW 语句创建（ORM 不映射视图）
# ─────────────────────────────────────────────────────────────
