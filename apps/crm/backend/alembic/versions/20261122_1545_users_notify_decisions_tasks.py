"""Staff Telegram switches for EDS tasks (GL-2): decisions default on, other tasks default off.

Existing rows get the defaults: decisions on, tasks off. Downgrade drops the columns.

Revision ID: 4d6593eef5f9
Revises: c41a7e5d9b20
Create Date: 2026-11-22 15:45:39.321711+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4d6593eef5f9"
down_revision: str | Sequence[str] | None = "c41a7e5d9b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_decisions", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("notify_tasks", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "notify_tasks")
    op.drop_column("users", "notify_decisions")
