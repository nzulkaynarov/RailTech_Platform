"""users.show_test (ТЕСТ-2): per-person switch «Показывать тестовые».

Additive: one boolean column with a false default; downgrade drops it.

Revision ID: 7d41a9c2e5b3
Revises: 3bc0ed1386fc
Create Date: 2026-11-27 11:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d41a9c2e5b3"
down_revision: str | Sequence[str] | None = "3bc0ed1386fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("show_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "show_test")
