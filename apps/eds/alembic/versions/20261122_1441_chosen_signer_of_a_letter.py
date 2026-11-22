"""ЕД-6: подписант письма выбран при создании — его и ждёт задача «Подписать».

Факт — `documents.chosen_signer_crm_user_id`; у старых писем `NULL`, подписанта по-прежнему подбирает реестр полномочий.

Revision ID: 151929c96b8f
Revises: c3a8e1f07d52
Create Date: 2026-11-22 14:41:20.718706+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "151929c96b8f"
down_revision: str | Sequence[str] | None = "c3a8e1f07d52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("chosen_signer_crm_user_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "chosen_signer_crm_user_id")
