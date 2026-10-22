"""rt_bus: таблицы шины событий; erp_incoming_events заменена inbox шины и erp_event_notices (B4)

Волна 11, этап B (ADR-0014): CRM публикует события клиента, контакта, сотрудника и лида через
outbox и принимает события ERP через inbox шины `rt_bus` (`POST /bus/v1/events`).

* `rt_bus_outbox`, `rt_bus_delivery`, `rt_bus_inbox`, `rt_bus_subscriber_state` — схема библиотеки
  (`rt_bus.sqlalchemy.bus_tables`), одинакова в CRM (SQLAlchemy) и ERP (Django), L9;
* `erp_event_notices` — сообщения в Telegram, посчитанные обработчиком события ERP: уходят после
  коммита обработки, без потерь при падении воркера и без дублей при автоповторе;
* `erp_incoming_events` удалена (карт-бланш владельца: данных прода нет; журнал вебхуков заменён
  inbox шины). Downgrade возвращает пустую таблицу в прежней форме, данные не восстанавливаются.

Revision ID: 0037_rt_bus
Revises: 0036_drop_user_platform_roles
Create Date: 2026-10-23 11:00:00+00:00
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_rt_bus"
down_revision: str | None = "0036_drop_user_platform_roles"
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

    op.create_table(
        "erp_event_notices",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "sent",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_erp_event_notices")),
    )
    op.create_index(
        "ix_erp_event_notices_pending",
        "erp_event_notices",
        ["created_at"],
        postgresql_where=sa.text("notified_at IS NULL"),
    )

    op.drop_index("ix_erp_incoming_events_body_sha256", table_name="erp_incoming_events")
    op.drop_index("ix_erp_incoming_events_status", table_name="erp_incoming_events")
    op.drop_index("ix_erp_incoming_events_crm_client_id", table_name="erp_incoming_events")
    op.drop_table("erp_incoming_events")


def downgrade() -> None:
    op.create_table(
        "erp_incoming_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("erp_company_id", sa.BigInteger(), nullable=True),
        sa.Column("crm_client_id", sa.BigInteger(), nullable=True),
        sa.Column("deal_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'received'"), nullable=False
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("outbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("body_sha256", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'failed', 'rejected', 'skipped')",
            name=op.f("ck_erp_incoming_events_status"),
        ),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_erp_incoming_events_crm_client_id", "erp_incoming_events", ["crm_client_id"]
    )
    op.create_index("ix_erp_incoming_events_status", "erp_incoming_events", ["status"])
    op.create_index("ix_erp_incoming_events_body_sha256", "erp_incoming_events", ["body_sha256"])

    op.drop_index("ix_erp_event_notices_pending", table_name="erp_event_notices")
    op.drop_table("erp_event_notices")
    op.drop_table("rt_bus_subscriber_state")
    op.drop_index("rt_bus_inbox_status_idx", table_name="rt_bus_inbox")
    op.drop_table("rt_bus_inbox")
    op.drop_index("rt_bus_delivery_sub_status_idx", table_name="rt_bus_delivery")
    op.drop_index("rt_bus_delivery_due_idx", table_name="rt_bus_delivery")
    op.drop_table("rt_bus_delivery")
    op.drop_index("rt_bus_outbox_pending_idx", table_name="rt_bus_outbox")
    op.drop_table("rt_bus_outbox")
