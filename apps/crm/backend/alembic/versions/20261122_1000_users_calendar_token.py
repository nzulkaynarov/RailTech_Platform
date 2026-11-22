"""Секретная ссылка на личный календарь: хеш токена в `users`.

`calendar_token_hash` — sha256 токена (уникален), `calendar_token_at` — когда выдан. Токен виден
один раз при выдаче. У прежних строк ссылки нет.

Downgrade удаляет колонки (выданные ссылки перестают действовать).

Revision ID: c41a7e5d9b20
Revises: 9b1daa0b361e
Create Date: 2026-11-22 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c41a7e5d9b20"
down_revision: str | Sequence[str] | None = "9b1daa0b361e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("calendar_token_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "users", sa.Column("calendar_token_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint("uq_users_calendar_token_hash", "users", ["calendar_token_hash"])


def downgrade() -> None:
    op.drop_constraint("uq_users_calendar_token_hash", "users", type_="unique")
    op.drop_column("users", "calendar_token_at")
    op.drop_column("users", "calendar_token_hash")
