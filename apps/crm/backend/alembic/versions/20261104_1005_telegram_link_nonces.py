"""Привязка Telegram контактом: погашенные токены и отключение уведомлений (NOTIFY-1, ADR-0023)

* `telegram_identities.notifications_off_at` — контакт отключил Telegram в кабинете: клиентские
  рассылки этот аккаунт не берут, пока он не подключён снова;
* `telegram_link_nonces` — nonce токена `/start tg_…` (первичный ключ: повтор и параллельный
  повтор ссылки отклоняет база),
  контакт CRM, Telegram, срок токена и время погашения. Токен и подпись не хранятся.

Откат: колонка и таблица удаляются (погашенные ссылки к тому времени просрочены — срок 15 минут).

Revision ID: 5d5089811bac
Revises: 97bc02846729
Create Date: 2026-11-04 10:05:12.023684+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d5089811bac"
down_revision: str | Sequence[str] | None = "97bc02846729"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "telegram_identities",
        sa.Column("notifications_off_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "telegram_link_nonces",
        sa.Column("nonce", sa.String(length=18), nullable=False),
        sa.Column("crm_contact_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("nonce", name=op.f("pk_telegram_link_nonces")),
    )


def downgrade() -> None:
    op.drop_table("telegram_link_nonces")
    op.drop_column("telegram_identities", "notifications_off_at")
