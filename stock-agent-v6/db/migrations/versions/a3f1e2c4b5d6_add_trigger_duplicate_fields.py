"""triggers: add duplicate_count + last_seen_at

Revision ID: a3f1e2c4b5d6
Revises: 8092f05d1359
Create Date: 2026-04-20 00:00:00.000000

目的：支持同主题（industry+type+日期）新 news 命中已存在 trigger 时的去重统计。
- duplicate_count：该行被新 news 再次命中的总次数（含首次=1）
- last_seen_at：最近一次新 news 再次命中时间（首次=created_at）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f1e2c4b5d6"
down_revision: Union[str, Sequence[str], None] = "8092f05d1359"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("triggers") as batch_op:
        batch_op.add_column(sa.Column(
            "duplicate_count", sa.Integer(),
            nullable=False, server_default=sa.text("1"),
        ))
        batch_op.add_column(sa.Column("last_seen_at", sa.DateTime(), nullable=True))
        # 查 (industry, type, DATE(created_at), mode) 需要索引
        batch_op.create_index(
            "ix_triggers_dedup",
            ["industry", "type", "mode", "created_at"],
            unique=False,
        )

    # 历史数据回填：last_seen_at 用 created_at 兜底
    op.execute("UPDATE triggers SET last_seen_at = created_at WHERE last_seen_at IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("triggers") as batch_op:
        batch_op.drop_index("ix_triggers_dedup")
        batch_op.drop_column("last_seen_at")
        batch_op.drop_column("duplicate_count")
