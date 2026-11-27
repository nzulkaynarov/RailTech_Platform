"""client is_test mark (ТЕСТ-1): projection of the ERP company mark `is_test`.

Additive: one boolean column with a false default; downgrade drops it.

Revision ID: 3bc0ed1386fc
Revises: 520841a91c2e
Create Date: 2026-11-27 07:33:55.411765+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3bc0ed1386fc"
down_revision: str | Sequence[str] | None = "520841a91c2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("is_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("clients", "is_test")
