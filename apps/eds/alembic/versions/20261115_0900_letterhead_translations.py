"""Бланк на трёх языках (TPL-3, план 2.7): варианты `uz` и `en` в `letterhead.translations` (JSONB).
Пусто у прежнего бланка — письма печатаются основным текстом, как раньше. Откат удаляет колонку.

Revision ID: f69980474676
Revises: 1ab826e3a38f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f69980474676"
down_revision: str | Sequence[str] | None = "1ab826e3a38f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "letterhead",
        sa.Column("translations", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("letterhead", "translations")
