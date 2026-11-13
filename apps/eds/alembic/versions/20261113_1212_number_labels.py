"""Обозначения номеров реестра (задача «Н», решение владельца 2026-11-13): таблица `number_labels`, строка на вид.
Строк нет — действуют умолчания кода (латиницей). Откат удаляет таблицу: номера снова с умолчаниями кода.

Revision ID: 87c14728e40c
Revises: 18acc897173a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "87c14728e40c"
down_revision: str | Sequence[str] | None = "18acc897173a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "number_labels",
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("label", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("number_labels")
