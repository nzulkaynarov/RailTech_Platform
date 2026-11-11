"""Текст письма общего ящика в карточке ВХ: исполнитель видит само письмо (решение владельца 2026-11-11).

Revision ID: 8e20e8a024d7
Revises: c1f4a9e2d7b3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e20e8a024d7"
down_revision: str | Sequence[str] | None = "c1f4a9e2d7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("letters", sa.Column("body_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("letters", "body_text")
