"""Б-9: отметка «счёт партнёра придёт позже» у служебки с суммой.

Факт — `documents.invoice_later`: автор отправил записку на оплату без файла счёта и сказал об этом явно; бухгалтер
видит отметку и напоминает автору, а не возвращает записку.

Revision ID: b9c2f4d81e07
Revises: a7d41c9e3b58
Create Date: 2026-11-25 15:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c2f4d81e07"
down_revision: str | Sequence[str] | None = "a7d41c9e3b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("invoice_later", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("documents", "invoice_later")
