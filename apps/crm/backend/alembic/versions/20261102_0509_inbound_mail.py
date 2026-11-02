"""Входящая почта общего ящика (W18A-P2, B-INB-5)

* `inbound_mail` — письма очереди «Входящая почта»: UNIQUE `message_id` (дедупликация), тело
  текстом, метаданные вложений (файлы — в бакете вложений CRM), связка с клиентом и лидом, подсказка
  помощника
  (`assist_*`), итог (ВХ, лид, архив);
* `inbound_mailbox` — UIDVALIDITY и последний UID папки (на сервере письма не помечаются), итог
  последнего опроса для строки здоровья;
* `email_log.thread_headers` — `In-Reply-To` и `References` ответа в ту же цепочку.

Откат удаляет таблицы и столбец (файлы вложений в хранилище остаются — ключи с префиксом `mail/`).

Revision ID: 377806fa51cd
Revises: b95ca021f2f0
Create Date: 2026-11-02 05:09:54.881066+00:00
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "377806fa51cd"
down_revision: str | Sequence[str] | None = "b95ca021f2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str) -> sa.Column[Any]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _json(name: str) -> sa.Column[Any]:
    return sa.Column(name, postgresql.JSONB(), server_default="[]", nullable=False)


def _fk(column: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{table}.id"],
        name=op.f(f"fk_inbound_mail_{column}_{table}"),
        ondelete="SET NULL",
    )


def upgrade() -> None:
    op.create_table(
        "inbound_mail",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("message_id", sa.String(length=500), nullable=False),
        sa.Column("mailbox", sa.String(length=200), nullable=False),
        sa.Column("uidvalidity", sa.BigInteger(), nullable=False),
        sa.Column("uid", sa.BigInteger(), nullable=False),
        sa.Column("from_email", sa.String(length=255), server_default="", nullable=False),
        sa.Column("from_name", sa.String(length=255), server_default="", nullable=False),
        _json("to_addrs"),
        sa.Column("subject", sa.String(length=300), server_default="", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _ts("received_at"),
        sa.Column("in_reply_to", sa.Text(), nullable=True),
        sa.Column("references", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        _json("attachments"),
        _json("skipped"),
        sa.Column("too_large", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("matched_lead_id", sa.BigInteger(), nullable=True),
        _json("inns"),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("assist_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("assist_kind", sa.String(length=16), nullable=True),
        sa.Column("assist_summary", sa.String(length=300), nullable=True),
        sa.Column("assist_action", sa.String(length=16), nullable=True),
        sa.Column("eds_letter_id", sa.String(length=64), nullable=True),
        sa.Column("eds_letter_number", sa.String(length=32), nullable=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("archive_reason", sa.String(length=500), nullable=True),
        sa.Column("handled_by", sa.BigInteger(), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "status IN ('new', 'registered', 'lead', 'archived')",
            name=op.f("ck_inbound_mail_status"),
        ),
        sa.CheckConstraint(
            "assist_status IN ('pending', 'done', 'unavailable', 'off')",
            name=op.f("ck_inbound_mail_assist_status"),
        ),
        _fk("client_id", "clients"),
        _fk("matched_lead_id", "leads"),
        _fk("lead_id", "leads"),
        sa.ForeignKeyConstraint(
            ["handled_by"],
            ["users.id"],
            name=op.f("fk_inbound_mail_handled_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_mail")),
    )
    op.create_index("uq_inbound_mail_message_id", "inbound_mail", ["message_id"], unique=True)
    op.create_index("ix_inbound_mail_status_received", "inbound_mail", ["status", "received_at"])
    op.execute(
        "CREATE TRIGGER trg_inbound_mail_updated_at BEFORE UPDATE ON inbound_mail "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.create_table(
        "inbound_mailbox",
        sa.Column("mailbox", sa.String(length=200), nullable=False),
        sa.Column("host", sa.String(length=253), server_default="", nullable=False),
        sa.Column("uidvalidity", sa.BigInteger(), nullable=True),
        sa.Column("last_uid", sa.BigInteger(), nullable=True),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_kind", sa.String(length=32), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("fetched_total", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("mailbox", name=op.f("pk_inbound_mailbox")),
    )
    op.add_column("email_log", sa.Column("thread_headers", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("email_log", "thread_headers")
    op.drop_table("inbound_mailbox")
    op.execute("DROP TRIGGER IF EXISTS trg_inbound_mail_updated_at ON inbound_mail")
    op.drop_index("ix_inbound_mail_status_received", table_name="inbound_mail")
    op.drop_index("uq_inbound_mail_message_id", table_name="inbound_mail")
    op.drop_table("inbound_mail")
