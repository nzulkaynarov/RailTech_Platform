"""Telegram client groups with a secretary bot (ADR-0032): `telegram_groups`.

One row per group the bot was made admin of; group messages live in `conversations`
(`channel = 'group'`, one per group) so a unique partial index guards that. Downgrade drops both.

Revision ID: 9c3f1d5a62e7
Revises: 51e8c6eed04d
Create Date: 2026-11-25 09:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c3f1d5a62e7"
down_revision: str | Sequence[str] | None = "51e8c6eed04d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_groups",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("chat_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(10), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=True),
        sa.Column("connect_code", sa.String(12), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bot_is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_pin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("topic_mode", sa.String(8), server_default=sa.text("'request'"), nullable=False),
        sa.Column("language", sa.String(2), nullable=True),
        sa.Column("notice_message_id", sa.BigInteger(), nullable=True),
        sa.Column("notice_pinned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bound_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("chat_id", name=op.f("pk_telegram_groups")),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_telegram_groups_client_id_clients"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bound_by_user_id"],
            ["users.id"],
            name=op.f("fk_telegram_groups_bound_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'bound', 'unbound', 'removed')",
            name=op.f("ck_telegram_groups_status"),
        ),
        sa.CheckConstraint(
            "topic_mode IN ('none', 'request')", name=op.f("ck_telegram_groups_topic_mode")
        ),
        sa.CheckConstraint(
            "language IS NULL OR language IN ('ru', 'uz', 'en')",
            name=op.f("ck_telegram_groups_language"),
        ),
        sa.CheckConstraint(
            "status <> 'bound' OR client_id IS NOT NULL",
            name=op.f("ck_telegram_groups_bound_has_client"),
        ),
        sa.UniqueConstraint("connect_code", name=op.f("uq_telegram_groups_connect_code")),
    )
    op.create_index("ix_telegram_groups_client_id", "telegram_groups", ["client_id"])
    op.execute(
        "CREATE TRIGGER trg_telegram_groups_updated_at BEFORE UPDATE ON telegram_groups "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.create_index(
        "uq_conversations_group_chat",
        "conversations",
        ["tg_chat_id"],
        unique=True,
        postgresql_where=sa.text("channel = 'group'"),
    )


def downgrade() -> None:
    op.drop_index("uq_conversations_group_chat", table_name="conversations")
    op.drop_index("ix_telegram_groups_client_id", table_name="telegram_groups")
    op.drop_table("telegram_groups")
