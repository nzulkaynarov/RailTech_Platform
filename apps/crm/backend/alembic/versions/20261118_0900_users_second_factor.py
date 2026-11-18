"""Второй фактор входа сотрудника (ДВ-4, реестр рисков Д1): поля TOTP в `users`.

Секрет приложения-аутентификатора — шифр Fernet ключом `SECRETS_KEY` (`totp_secret`, начатая
настройка — `totp_pending_secret`); `totp_enabled_at` — включён и с какого момента;
`totp_last_step` — последний принятый шаг 30 с; `totp_backup_codes` — sha256 резервных кодов.
У прежних строк фактор выключен.

Downgrade удаляет колонки (включённые факторы теряются).

Revision ID: 8d58823f6312
Revises: 87bb4c6ed643
Create Date: 2026-11-18 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8d58823f6312"
down_revision: str | Sequence[str] | None = "87bb4c6ed643"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("totp_pending_secret", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "totp_backup_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "totp_pending_secret")
    op.drop_column("users", "totp_secret")
