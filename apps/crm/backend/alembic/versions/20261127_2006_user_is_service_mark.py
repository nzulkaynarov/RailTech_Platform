"""user is_service mark (ДОСТ-1п): additive boolean, false by default; downgrade drops it.

Revision ID: ec7e70368e81
Revises: 3bc0ed1386fc
Create Date: 2026-11-27 20:06:34.380560+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ec7e70368e81"
down_revision: str | Sequence[str] | None = "3bc0ed1386fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_service", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "is_service")
