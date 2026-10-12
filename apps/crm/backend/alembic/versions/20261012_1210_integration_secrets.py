"""integration_secrets, telegram_chat_candidates: «Подключения» (аудит 2026-10-12)

Revision ID: 0010_integration_secrets
Revises: 0009_service_request_resolution
Create Date: 2026-10-12 12:10:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_integration_secrets"
down_revision: str | Sequence[str] | None = "0009_service_request_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integration_secrets",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("last4", sa.String(length=4), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_integration_secrets_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_integration_secrets")),
    )
    op.create_table(
        "telegram_chat_candidates",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("chat_type", sa.String(length=16), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("chat_id", name=op.f("pk_telegram_chat_candidates")),
    )


def downgrade() -> None:
    op.drop_table("telegram_chat_candidates")
    op.drop_table("integration_secrets")
