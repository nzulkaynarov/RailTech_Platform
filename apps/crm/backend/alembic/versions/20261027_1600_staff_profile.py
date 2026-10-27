"""staff_profile: телефон, пояс, подпись, фото, замещение, привязка Telegram и сброс пароля (W15-H6)

Профиль, который правит сам сотрудник: `users.phone`, `timezone` (по умолчанию Asia/Tashkent),
`email_signature`, `tg_username`, фото (`avatar_key`, `avatar_updated_at`) и замещение
(`deputy_user_id`, `deputy_from`, `deputy_to`). Две таблицы с хешами одноразовых секретов:
`staff_telegram_links` (код привязки Telegram, 10 минут) и `password_reset_tokens` (ссылка сброса
пароля, 60 минут). Данных для переноса нет.

Revision ID: 0042_staff_profile
Revises: 0041_external_cause_alerts
Create Date: 2026-10-27 16:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_staff_profile"
down_revision: str | None = "0041_external_cause_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEPUTY_CHECK = (
    "(deputy_user_id IS NULL AND deputy_from IS NULL AND deputy_to IS NULL) OR "
    "(deputy_from IS NOT NULL AND deputy_to IS NOT NULL AND deputy_from <= deputy_to "
    "AND (deputy_user_id IS NULL OR deputy_user_id <> id))"
)


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Tashkent'"),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("email_signature", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("tg_username", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("tg_linked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("avatar_key", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("avatar_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("deputy_user_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("deputy_from", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("deputy_to", sa.Date(), nullable=True))
    op.add_column(
        "users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_users_deputy_user_id_users"),
        "users",
        "users",
        ["deputy_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(op.f("ck_users_deputy_period"), "users", _DEPUTY_CHECK)
    op.create_index("ix_users_deputy_user_id", "users", ["deputy_user_id"])

    op.create_table(
        "staff_telegram_links",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_staff_telegram_links_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_telegram_links")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_staff_telegram_links_code_hash")),
    )
    op.create_index("ix_staff_telegram_links_user_id", "staff_telegram_links", ["user_id"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'telegram')", name=op.f("ck_password_reset_tokens_channel")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_reset_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_reset_tokens_token_hash")),
    )
    op.create_index(
        "ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_staff_telegram_links_user_id", table_name="staff_telegram_links")
    op.drop_table("staff_telegram_links")
    op.drop_index("ix_users_deputy_user_id", table_name="users")
    op.drop_constraint(op.f("ck_users_deputy_period"), "users", type_="check")
    op.drop_constraint(op.f("fk_users_deputy_user_id_users"), "users", type_="foreignkey")
    for column in (
        "password_changed_at",
        "deputy_to",
        "deputy_from",
        "deputy_user_id",
        "avatar_updated_at",
        "avatar_key",
        "tg_linked_at",
        "tg_username",
        "email_signature",
        "timezone",
        "phone",
    ):
        op.drop_column("users", column)
