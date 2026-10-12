"""escalations: чат поста и показанный приоритет; users: отказ Telegram в личке (аудит 2026-10-12)

Посты до миграции остаются с `channel_chat_id IS NULL`: их правят в канале из настроек.

Revision ID: 0016_channel_chat
Revises: 0015_deals
Create Date: 2026-10-12 14:20:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_channel_chat"
down_revision: str | None = "0015_deals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("escalations", sa.Column("channel_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("escalations", sa.Column("posted_priority", sa.String(8), nullable=True))
    op.add_column("users", sa.Column("tg_dm_failed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "tg_dm_failed_at")
    op.drop_column("escalations", "posted_priority")
    op.drop_column("escalations", "channel_chat_id")
