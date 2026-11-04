"""Чат кабинета: беседа канала `cabinet` на клиента (CHAT-1, ADR-0023)

* `conversations.client_id` — клиент беседы кабинета (FK, при удалении клиента — NULL);
* `conversations.erp_company_id` — компания ERP беседы кабинета: по ней находится беседа, пока
  компания не сопоставлена клиенту CRM (сообщение не теряется);
* `conversations.tg_chat_id` — NULL допустим (у беседы кабинета чата Telegram нет); у беседы
  `telegram` он по-прежнему обязателен (CHECK);
* одна беседа `cabinet` на клиента и на компанию ERP — частичные уникальные индексы.

Откат: беседы кабинета (без чата Telegram) удаляются вместе с сообщениями, колонки и индексы — тоже,
`tg_chat_id` снова NOT NULL.

Revision ID: aafce74f2f2d
Revises: 97bc02846729
Create Date: 2026-11-04 09:43:58.092964+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "aafce74f2f2d"
down_revision: str | Sequence[str] | None = "97bc02846729"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "client_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "clients.id", ondelete="SET NULL", name="fk_conversations_client_id_clients"
            ),
            nullable=True,
        ),
    )
    op.add_column("conversations", sa.Column("erp_company_id", sa.BigInteger(), nullable=True))
    op.alter_column("conversations", "tg_chat_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_check_constraint(
        op.f("ck_conversations_telegram_chat"),
        "conversations",
        "channel <> 'telegram' OR tg_chat_id IS NOT NULL",
    )
    op.create_index(
        "uq_conversations_cabinet_client",
        "conversations",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("channel = 'cabinet' AND client_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversations_cabinet_company",
        "conversations",
        ["erp_company_id"],
        unique=True,
        postgresql_where=sa.text("channel = 'cabinet' AND erp_company_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_conversations_cabinet_company", table_name="conversations")
    op.drop_index("uq_conversations_cabinet_client", table_name="conversations")
    op.drop_constraint(op.f("ck_conversations_telegram_chat"), "conversations", type_="check")
    op.execute("DELETE FROM conversations WHERE tg_chat_id IS NULL")
    op.alter_column("conversations", "tg_chat_id", existing_type=sa.BigInteger(), nullable=False)
    op.drop_column("conversations", "erp_company_id")
    op.drop_column("conversations", "client_id")
