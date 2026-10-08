"""leads, telegram_identities, conversations, messages, tg_updates, lead_notes, settings (Фаза 2)

Revision ID: 0003_leads
Revises: 0002_kb
Create Date: 2026-10-08 14:58:16.348543+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_leads"
down_revision: str | Sequence[str] | None = "0002_kb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPDATED_AT_TABLES = ("leads", "telegram_identities", "conversations", "messages", "lead_notes")


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "display_name", sa.String(length=255), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("language", sa.String(length=2), server_default=sa.text("'ru'"), nullable=False),
        sa.Column(
            "language_confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("language_candidate", sa.String(length=2), nullable=True),
        sa.Column("stage", sa.String(length=16), server_default=sa.text("'new'"), nullable=False),
        sa.Column("score", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "owner_mode", sa.String(length=8), server_default=sa.text("'bot'"), nullable=False
        ),
        sa.Column("assigned_user_id", sa.BigInteger(), nullable=True),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_version", sa.String(length=32), nullable=True),
        sa.Column("need_summary", sa.Text(), nullable=True),
        sa.Column(
            "product_interest",
            postgresql.ARRAY(sa.String(length=64)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "qualification",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_fallbacks", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "bot_turns_without_progress", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_lead_msg_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_bot_msg_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_human_msg_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unresponsive_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handoff_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source", sa.String(length=16), server_default=sa.text("'telegram'"), nullable=False
        ),
        sa.Column("notes_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("language IN ('ru', 'uz', 'en')", name=op.f("ck_leads_language")),
        sa.CheckConstraint(
            "owner_mode IN ('bot', 'human', 'paused')", name=op.f("ck_leads_owner_mode")
        ),
        sa.CheckConstraint(
            "stage IN ('new','engaged','qualified','handoff','in_progress',"
            "'won','customer','lost','unresponsive')",
            name=op.f("ck_leads_stage"),
        ),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name=op.f("ck_leads_score")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
    )
    op.create_index("ix_leads_last_lead_msg_at", "leads", ["last_lead_msg_at"], unique=False)
    op.create_index("ix_leads_stage", "leads", ["stage"], unique=False)
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.create_table(
        "tg_updates",
        sa.Column("update_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("update_id", name=op.f("pk_tg_updates")),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "channel", sa.String(length=16), server_default=sa.text("'telegram'"), nullable=False
        ),
        sa.Column("tg_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("is_open", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_conversations_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_index("ix_conversations_lead_id", "conversations", ["lead_id"], unique=False)
    op.create_table(
        "lead_notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("visible_to_bot", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["leads.id"], name=op.f("fk_lead_notes_lead_id_leads"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_notes")),
    )
    op.create_index("ix_lead_notes_lead_id", "lead_notes", ["lead_id"], unique=False)
    op.create_table(
        "telegram_identities",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_username", sa.String(length=64), nullable=True),
        sa.Column("tg_first_name", sa.String(length=255), nullable=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("phone_e164", sa.String(length=20), nullable=True),
        sa.Column("verified_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_telegram_identities_lead_id_leads"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_identities")),
        sa.UniqueConstraint("tg_user_id", name=op.f("uq_telegram_identities_tg_user_id")),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('lead', 'bot', 'manager', 'system')", name=op.f("ck_messages_role")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index(
        "ix_messages_conversation_id_id", "messages", ["conversation_id", "id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_kb_gaps_lead_id_leads"),
        "kb_gaps",
        "leads",
        ["lead_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_kb_gaps_lead_id_leads"), "kb_gaps", type_="foreignkey")
    op.drop_index("ix_messages_conversation_id_id", table_name="messages")
    op.drop_table("messages")
    op.drop_table("telegram_identities")
    op.drop_index("ix_lead_notes_lead_id", table_name="lead_notes")
    op.drop_table("lead_notes")
    op.drop_index("ix_conversations_lead_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("tg_updates")
    op.drop_table("settings")
    op.drop_index("ix_leads_stage", table_name="leads")
    op.drop_index("ix_leads_last_lead_msg_at", table_name="leads")
    op.drop_table("leads")
