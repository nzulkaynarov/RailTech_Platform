"""ГЛ-0: настройка компании «автор может подписать своё письмо» (ADR-0024 п. 3).

Факт — `docflow_settings.author_may_sign_own_letter`; по умолчанию включено (решение владельца 2026-11-22):
автор с правом подписи подписывает своё письмо сам. Выключено — действует строгое правило «автор ≠ подписант».

Revision ID: a7d41c9e3b58
Revises: 151929c96b8f
Create Date: 2026-11-22 17:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d41c9e3b58"
down_revision: str | Sequence[str] | None = "151929c96b8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "docflow_settings",
        sa.Column("author_may_sign_own_letter", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("docflow_settings", "author_may_sign_own_letter")
