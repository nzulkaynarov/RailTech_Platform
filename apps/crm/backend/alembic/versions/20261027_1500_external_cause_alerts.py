"""external_cause_alerts: журнал причин сбоев и дедупликация оповещений (W15-H3)

Одна строка — один эпизод «Сломано» по причине (`cause_key`: общий корень нескольких сервисов,
например `vendor.anthropic:key_rejected`). Пока строка открыта, оповещение о причине уходит один
раз (`alerted_at`) — и по рестарту процесса не повторяется; закрытие (`ended_at`) шлёт одно
«восстановлено» (`recovery_alerted_at`). Данных для переноса нет.

Revision ID: 0041_external_cause_alerts
Revises: 0040_identity_catalog_state
Create Date: 2026-10-27 15:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_external_cause_alerts"
down_revision: str | None = "0040_identity_catalog_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_cause_alerts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("cause_key", sa.String(length=96), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column(
            "service_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_cause_alerts")),
    )
    op.create_index(
        "ix_external_cause_alerts_cause_started",
        "external_cause_alerts",
        ["cause_key", "started_at"],
    )
    op.create_index(
        "uq_external_cause_alerts_open",
        "external_cause_alerts",
        ["cause_key"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_external_cause_alerts_open", table_name="external_cause_alerts")
    op.drop_index("ix_external_cause_alerts_cause_started", table_name="external_cause_alerts")
    op.drop_table("external_cause_alerts")
