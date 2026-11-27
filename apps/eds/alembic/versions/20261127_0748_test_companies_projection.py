"""ТЕСТ-1: company_marks - projection of the ERP company mark `is_test` (test companies leave working lists).

Additive table; downgrade drops it.

Revision ID: b00c9b750a79
Revises: b9c2f4d81e07
Create Date: 2026-11-27 07:48:30.065203+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b00c9b750a79"
down_revision: str | Sequence[str] | None = "b9c2f4d81e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company_marks",
        sa.Column("erp_company_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("is_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("erp_company_id", name=op.f("pk_company_marks")),
    )


def downgrade() -> None:
    op.drop_table("company_marks")
