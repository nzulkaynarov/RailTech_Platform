"""client_notices: подтверждение запроса, «Заявка принята», приглашение в кабинет и их итог (D1-9)

* `client_notices` — сообщения клиенту от системы: канал, статус, код причины сбоя, ссылка на
  письмо в `email_log`;
* `leads.first_response_due_at` / `first_response_notified_at` — срок первого ответа на запрос
  с сайта и отметка «о просрочке написали» (SLA из `settings.web_form.first_response_sla_minutes`);
* `client_contacts.preferred_channel` — предпочитаемый канал контакта: telegram, email или both.

Данных для переноса нет: у существующих лидов срок не заводится.

Revision ID: 0044_client_notices
Revises: 0043_messages_bot_created_idx
Create Date: 2026-10-28 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044_client_notices"
down_revision: str | None = "0043_messages_bot_created_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_notices",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column(
            "status", sa.String(length=8), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("error", sa.String(length=64), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("email_log_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('web_confirmation', 'request_accepted', 'portal_invite')",
            name=op.f("ck_client_notices_kind"),
        ),
        sa.CheckConstraint(
            "channel IN ('telegram', 'email', 'both', 'none')",
            name=op.f("ck_client_notices_channel"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'skipped')",
            name=op.f("ck_client_notices_status"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_client_notices_lead_id_leads"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_client_notices_client_id_clients"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["client_contacts.id"],
            name=op.f("fk_client_notices_contact_id_client_contacts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["email_log_id"],
            ["email_log.id"],
            name=op.f("fk_client_notices_email_log_id_email_log"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_client_notices_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_client_notices")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_client_notices_dedupe_key")),
    )
    op.create_index("ix_client_notices_lead_id_kind", "client_notices", ["lead_id", "kind"])
    op.create_index("ix_client_notices_client_id_kind", "client_notices", ["client_id", "kind"])
    op.execute(
        "CREATE TRIGGER trg_client_notices_updated_at BEFORE UPDATE ON client_notices "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.add_column(
        "leads", sa.Column("first_response_due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("first_response_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "client_contacts", sa.Column("preferred_channel", sa.String(length=8), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_client_contacts_preferred_channel"),
        "client_contacts",
        "preferred_channel IS NULL OR preferred_channel IN ('telegram', 'email', 'both')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_client_contacts_preferred_channel"), "client_contacts", type_="check"
    )
    op.drop_column("client_contacts", "preferred_channel")
    op.drop_column("leads", "first_response_notified_at")
    op.drop_column("leads", "first_response_due_at")
    op.drop_table("client_notices")
