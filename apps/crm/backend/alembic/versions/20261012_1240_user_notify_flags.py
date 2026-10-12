"""users: подписки на личные уведомления; leads: время последнего уведомления менеджера (Q-010)

Revision ID: 0013_user_notify_flags
Revises: 0011_llm_usage
Create Date: 2026-10-12 12:40:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_user_notify_flags"
down_revision: str | None = "0011_llm_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notify_system", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("notify_leads", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "leads", sa.Column("manager_notified_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("leads", "manager_notified_at")
    op.drop_column("users", "notify_leads")
    op.drop_column("users", "notify_system")
