"""Журнал доставки `email_log` — один отправитель ансамбля (W18A-P1, B-INB-6)

ERP и EDS письма сами больше не шлют: публикуют `uz.railtech.<домен>.mail.requested.v1`, почтовый
сервис CRM доставляет их через SMTP карточки «Почта». В журнале появляются:

* `source` — система-источник (`crm`, `erp`, `eds`; у прежних строк — `crm`);
* `purpose` — назначение письма (код шаблона отправителя), `ref_kind`/`ref_id` — его объект,
  `reply_to` — адрес для ответа;
* `request_key` — ключ идемпотентности отправителя: UNIQUE (`source`, `request_key`), повтор события
  второго письма не даёт; `bus_event_id` — событие запроса (постановка в очередь после коммита);
* `notify` — нужен ли отправителю итог (`uz.railtech.crm.mail.sent|failed.v1`);
* `html_ciphertext`, `links_ciphertext` — HTML и ссылки на вложения шифртекстом `SECRETS_KEY`
  (как тело), стираются после отправки; `attachments` — только метаданные (имя, тип, размер,
  sha256).

`to_email` расширен до текста: в запросе до 10 адресов. Откат удаляет новые столбцы и строки,
пришедшие не из CRM (их получатели в узкий столбец могут не поместиться).

Revision ID: ac71231f330f
Revises: 9362ca08ba13
Create Date: 2026-10-28 12:16:55.566647+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ac71231f330f"
down_revision: str | Sequence[str] | None = "9362ca08ba13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_log",
        sa.Column("source", sa.String(16), nullable=False, server_default="crm"),
    )
    op.add_column("email_log", sa.Column("purpose", sa.String(64)))
    op.add_column("email_log", sa.Column("request_key", sa.String(128)))
    op.add_column("email_log", sa.Column("bus_event_id", sa.String(64)))
    op.add_column("email_log", sa.Column("ref_kind", sa.String(32)))
    op.add_column("email_log", sa.Column("ref_id", sa.String(64)))
    op.add_column("email_log", sa.Column("reply_to", sa.String(255)))
    op.add_column(
        "email_log",
        sa.Column("notify", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("email_log", sa.Column("html_ciphertext", sa.LargeBinary()))
    op.add_column("email_log", sa.Column("links_ciphertext", sa.LargeBinary()))
    op.add_column("email_log", sa.Column("attachments", postgresql.JSONB()))
    op.alter_column("email_log", "to_email", type_=sa.Text(), existing_nullable=False)
    op.create_check_constraint(
        op.f("ck_email_log_source"), "email_log", "source IN ('crm', 'erp', 'eds')"
    )
    op.create_index(
        "uq_email_log_request",
        "email_log",
        ["source", "request_key"],
        unique=True,
        postgresql_where=sa.text("request_key IS NOT NULL"),
    )
    op.create_index(
        "ix_email_log_bus_event",
        "email_log",
        ["bus_event_id"],
        postgresql_where=sa.text("bus_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM email_log WHERE source <> 'crm'")
    op.drop_index("ix_email_log_bus_event", table_name="email_log")
    op.drop_index("uq_email_log_request", table_name="email_log")
    op.drop_constraint(op.f("ck_email_log_source"), "email_log", type_="check")
    op.alter_column("email_log", "to_email", type_=sa.String(255), existing_nullable=False)
    for column in (
        "attachments",
        "links_ciphertext",
        "html_ciphertext",
        "notify",
        "reply_to",
        "ref_id",
        "ref_kind",
        "bus_event_id",
        "request_key",
        "purpose",
        "source",
    ):
        op.drop_column("email_log", column)
