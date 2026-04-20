"""phase 6 event queue: triggers.status + news_items.consumed

Revision ID: 217751d42ff2
Revises: e5cf09a4f79a
Create Date: 2026-04-19 15:33:48.671937
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "217751d42ff2"
down_revision: Union[str, Sequence[str], None] = "e5cf09a4f79a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── news_items：加 consumed_by_trigger_id + consumed_at ──
    with op.batch_alter_table("news_items") as batch_op:
        batch_op.add_column(sa.Column("consumed_by_trigger_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("consumed_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_news_consumed", ["consumed_by_trigger_id"], unique=False)
        batch_op.create_index("ix_news_pending", ["consumed_by_trigger_id", "created_at"], unique=False)
        batch_op.create_foreign_key(
            "fk_news_items_consumed_by_trigger",
            "triggers",
            ["consumed_by_trigger_id"],
            ["id"],
        )

    # ── triggers：status / consumed_by_run_id / priority / processed_at ──
    # NOT NULL 列必须带 server_default，否则已有行会报错
    with op.batch_alter_table("triggers") as batch_op:
        batch_op.add_column(sa.Column(
            "status", sa.String(),
            nullable=False, server_default=sa.text("'pending'"),
        ))
        batch_op.add_column(sa.Column("consumed_by_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column(
            "priority", sa.Integer(),
            nullable=False, server_default=sa.text("5"),
        ))
        batch_op.add_column(sa.Column("processed_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_triggers_consumed_by_run",
            "runs",
            ["consumed_by_run_id"],
            ["id"],
        )

    # 历史数据修正：已有 triggers.run_id 不为空的视为"旧模型产生-已消费"，回填字段
    op.execute(
        "UPDATE triggers SET status='completed', consumed_by_run_id=run_id, "
        "processed_at=created_at WHERE run_id IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("triggers") as batch_op:
        batch_op.drop_constraint("fk_triggers_consumed_by_run", type_="foreignkey")
        batch_op.drop_column("processed_at")
        batch_op.drop_column("priority")
        batch_op.drop_column("consumed_by_run_id")
        batch_op.drop_column("status")

    with op.batch_alter_table("news_items") as batch_op:
        batch_op.drop_constraint("fk_news_items_consumed_by_trigger", type_="foreignkey")
        batch_op.drop_index("ix_news_pending")
        batch_op.drop_index("ix_news_consumed")
        batch_op.drop_column("consumed_at")
        batch_op.drop_column("consumed_by_trigger_id")
