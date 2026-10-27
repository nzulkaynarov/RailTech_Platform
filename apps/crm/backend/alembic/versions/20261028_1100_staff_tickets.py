"""staff_tickets: обращения сотрудников, уведомления сотрудникам, флаг тура (W15-H7)

Три таблицы: `staff_tickets` (тема, текст, страница, роль автора, статус «Новое / В работе /
Решено»), `staff_ticket_messages` (ответы админа) и `staff_notifications` (общая лента событий CRM
для колокольчика Платформы: ответ на обращение, привязка Telegram). Колонка
`users.onboarding_done_at` — «Больше не показывать» тур первого входа; у существующих сотрудников
она заполняется сразу, приветствие увидят только новые.

Revision ID: 0044_staff_tickets
Revises: 0043_messages_bot_created_idx
Create Date: 2026-10-28 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_staff_tickets"
down_revision: str | None = "0043_messages_bot_created_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("onboarding_done_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE users SET onboarding_done_at = now()")

    op.create_table(
        "staff_tickets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("page", sa.String(length=300), nullable=True),
        sa.Column("author_role", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "subject IN ('access', 'notification', 'template', 'error', 'other')",
            name=op.f("ck_staff_tickets_subject"),
        ),
        sa.CheckConstraint(
            "status IN ('new', 'in_progress', 'resolved')", name=op.f("ck_staff_tickets_status")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_staff_tickets_author_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_tickets")),
    )
    op.create_index("ix_staff_tickets_author_id", "staff_tickets", ["author_id", "created_at"])
    op.create_index("ix_staff_tickets_status", "staff_tickets", ["status", "updated_at"])

    op.create_table(
        "staff_ticket_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("ticket_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["staff_tickets.id"],
            name=op.f("fk_staff_ticket_messages_ticket_id_staff_tickets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_staff_ticket_messages_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_ticket_messages")),
    )
    op.create_index(
        "ix_staff_ticket_messages_ticket_id", "staff_ticket_messages", ["ticket_id", "created_at"]
    )

    op.create_table(
        "staff_notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("tab", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=200), nullable=True),
        sa.Column("object_kind", sa.String(length=20), nullable=True),
        sa.Column("object_id", sa.String(length=40), nullable=True),
        sa.Column("object_number", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "tab IN ('decisions', 'clients', 'system')", name=op.f("ck_staff_notifications_tab")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_staff_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_notifications")),
    )
    op.create_index(
        "ix_staff_notifications_user_id", "staff_notifications", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_staff_notifications_user_id", table_name="staff_notifications")
    op.drop_table("staff_notifications")
    op.drop_index("ix_staff_ticket_messages_ticket_id", table_name="staff_ticket_messages")
    op.drop_table("staff_ticket_messages")
    op.drop_index("ix_staff_tickets_status", table_name="staff_tickets")
    op.drop_index("ix_staff_tickets_author_id", table_name="staff_tickets")
    op.drop_table("staff_tickets")
    op.drop_column("users", "onboarding_done_at")
