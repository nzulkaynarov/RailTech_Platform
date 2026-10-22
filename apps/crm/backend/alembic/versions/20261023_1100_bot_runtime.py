"""bot_runtime: состояние процесса бота и запрос на перезапуск (S0-4)

Бот переехал из процесса `crm-api` в отдельный `crm-bot`. Процессы не знают друг о друге, поэтому
общаются через одну строку этой таблицы: `crm-bot` пишет, что он делает и свой пульс, `crm-api`
пишет «токен сменили — перезапусти» (`restart_requested_at`). Значения токена в таблице нет.

Revision ID: 0037_bot_runtime
Revises: 0036_drop_user_platform_roles
Create Date: 2026-10-23 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_bot_runtime"
down_revision: str | None = "0036_drop_user_platform_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_runtime",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("running", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=True),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("last_error", sa.String(160), nullable=True),
        sa.Column("profile", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restart_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restart_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name=op.f("ck_bot_runtime_single_row")),
    )


def downgrade() -> None:
    op.drop_table("bot_runtime")
