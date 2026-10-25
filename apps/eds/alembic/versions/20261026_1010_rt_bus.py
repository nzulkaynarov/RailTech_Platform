"""rt_bus: таблицы шины событий

Волна 12, E2 (ADR-0014): EDS публикует события своих сущностей через outbox и принимает чужие через inbox
шины `rt_bus` (`POST /bus/v1/events`). Схема — библиотечная (`rt_bus.sqlalchemy.bus_tables`), одинакова в CRM,
ERP и EDS (L9); тест сравнивает эту миграцию с метаданными моделей.

Revision ID: 0002_rt_bus
Revises: 0001_init
Create Date: 2026-10-26 10:10:00+00:00
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_rt_bus"
down_revision: str | Sequence[str] | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, *, nullable: bool) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "rt_bus_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _ts("created_at", nullable=False),
        _ts("dispatched_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="rt_bus_outbox_pkey"),
    )
    op.create_index(
        "rt_bus_outbox_pending_idx",
        "rt_bus_outbox",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )

    op.create_table(
        "rt_bus_delivery",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("subscriber", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        _ts("next_attempt_at", nullable=True),
        _ts("lease_until", nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        _ts("last_attempt_at", nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _ts("delivered_at", nullable=True),
        _ts("created_at", nullable=False),
        _ts("updated_at", nullable=False),
        sa.PrimaryKeyConstraint("id", name="rt_bus_delivery_pkey"),
        sa.UniqueConstraint("event_id", "subscriber", name="rt_bus_delivery_event_sub_uniq"),
    )
    op.create_index("rt_bus_delivery_due_idx", "rt_bus_delivery", ["status", "next_attempt_at"])
    op.create_index("rt_bus_delivery_sub_status_idx", "rt_bus_delivery", ["subscriber", "status"])

    op.create_table(
        "rt_bus_inbox",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("publisher", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("next_attempt_at", nullable=True),
        _ts("received_at", nullable=False),
        _ts("processed_at", nullable=True),
        _ts("updated_at", nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="rt_bus_inbox_pkey"),
    )
    op.create_index("rt_bus_inbox_status_idx", "rt_bus_inbox", ["status", "received_at"])

    op.create_table(
        "rt_bus_subscriber_state",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("subscriber", sa.String(length=64), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        _ts("paused_until", nullable=True),
        _ts("last_failure_at", nullable=True),
        _ts("last_success_at", nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _ts("updated_at", nullable=False),
        sa.PrimaryKeyConstraint("id", name="rt_bus_subscriber_state_pkey"),
        sa.UniqueConstraint("subscriber", name="rt_bus_subscriber_state_uniq"),
    )


def downgrade() -> None:
    op.drop_table("rt_bus_subscriber_state")
    op.drop_index("rt_bus_inbox_status_idx", table_name="rt_bus_inbox")
    op.drop_table("rt_bus_inbox")
    op.drop_index("rt_bus_delivery_sub_status_idx", table_name="rt_bus_delivery")
    op.drop_index("rt_bus_delivery_due_idx", table_name="rt_bus_delivery")
    op.drop_table("rt_bus_delivery")
    op.drop_index("rt_bus_outbox_pending_idx", table_name="rt_bus_outbox")
    op.drop_table("rt_bus_outbox")
