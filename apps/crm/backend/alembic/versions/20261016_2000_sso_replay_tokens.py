"""sso_replay_tokens: одноразовые jti SSO-токенов (M3-CRM-06, CONTRACTS §6)

Revision ID: 0025_sso_replay_tokens
Revises: 0024_erp_incoming_events
Create Date: 2026-10-16 20:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_sso_replay_tokens"
down_revision: str | None = "0024_erp_incoming_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sso_replay_tokens",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index("ix_sso_replay_tokens_created_at", "sso_replay_tokens", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_sso_replay_tokens_created_at", table_name="sso_replay_tokens")
    op.drop_table("sso_replay_tokens")
