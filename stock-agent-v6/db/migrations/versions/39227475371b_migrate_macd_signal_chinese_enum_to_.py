"""migrate macd_signal chinese enum to english

Revision ID: 39227475371b
Revises: 217751d42ff2
Create Date: 2026-04-19 16:10:27.407012

把 technical_snapshots.macd_signal 的历史中文值（金叉/死叉/无交叉）统一替换为英文枚举
（golden_cross/death_cross/no_cross）。幂等：多次运行无副作用。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "39227475371b"
down_revision: Union[str, Sequence[str], None] = "217751d42ff2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 中文 → 英文枚举
    op.execute("UPDATE technical_snapshots SET macd_signal='golden_cross' WHERE macd_signal='金叉'")
    op.execute("UPDATE technical_snapshots SET macd_signal='death_cross'  WHERE macd_signal='死叉'")
    op.execute("UPDATE technical_snapshots SET macd_signal='no_cross'     WHERE macd_signal='无交叉'")


def downgrade() -> None:
    # 仅在明确要回滚到旧代码时才用；新代码不再接受中文枚举
    op.execute("UPDATE technical_snapshots SET macd_signal='金叉'   WHERE macd_signal='golden_cross'")
    op.execute("UPDATE technical_snapshots SET macd_signal='死叉'   WHERE macd_signal='death_cross'")
    op.execute("UPDATE technical_snapshots SET macd_signal='无交叉' WHERE macd_signal='no_cross'")
