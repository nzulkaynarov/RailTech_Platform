"""Таблицы rt_bus для SQLAlchemy — на переданном `MetaData` (`Base.metadata`), чтобы Alembic сервиса видел их
автогенерацией. Схема совпадает с миграцией Django (`rt_bus/django/migrations/0001_initial.py`), L9.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from .. import sql


@dataclass(frozen=True)
class BusTables:
    outbox: Table
    delivery: Table
    inbox: Table
    subscriber_state: Table


def _ts(name: str, nullable: bool) -> Column[datetime]:
    return Column(name, DateTime(timezone=True), nullable=nullable)


def bus_tables(metadata: MetaData) -> BusTables:
    """Объявить (или вернуть уже объявленные) таблицы rt_bus на `metadata`."""
    if sql.OUTBOX in metadata.tables:
        return BusTables(
            metadata.tables[sql.OUTBOX],
            metadata.tables[sql.DELIVERY],
            metadata.tables[sql.INBOX],
            metadata.tables[sql.STATE],
        )
    outbox = Table(
        sql.OUTBOX,
        metadata,
        Column("id", Uuid(as_uuid=True), nullable=False),
        Column("type", String(200), nullable=False),
        Column("source", String(100), nullable=False),
        Column("subject", String(200), nullable=True),
        Column("correlation_id", String(128), nullable=False),
        Column("envelope", JSONB, nullable=False),
        _ts("created_at", False),
        _ts("dispatched_at", True),
        PrimaryKeyConstraint("id", name="rt_bus_outbox_pkey"),
        Index("rt_bus_outbox_pending_idx", "created_at", postgresql_where=text("dispatched_at IS NULL")),
    )
    delivery = Table(
        sql.DELIVERY,
        metadata,
        Column("id", BigInteger, Identity(always=False), nullable=False),
        Column("event_id", Uuid(as_uuid=True), nullable=False),
        Column("event_type", String(200), nullable=False),
        Column("subscriber", String(64), nullable=False),
        Column("status", String(16), nullable=False),
        Column("attempts", Integer, nullable=False),
        _ts("next_attempt_at", True),
        _ts("lease_until", True),
        Column("lease_token", Uuid(as_uuid=True), nullable=True),
        _ts("last_attempt_at", True),
        Column("last_status_code", Integer, nullable=True),
        Column("last_error", Text, nullable=True),
        _ts("delivered_at", True),
        _ts("created_at", False),
        _ts("updated_at", False),
        PrimaryKeyConstraint("id", name="rt_bus_delivery_pkey"),
        UniqueConstraint("event_id", "subscriber", name="rt_bus_delivery_event_sub_uniq"),
        Index("rt_bus_delivery_due_idx", "status", "next_attempt_at"),
        Index("rt_bus_delivery_sub_status_idx", "subscriber", "status"),
    )
    inbox = Table(
        sql.INBOX,
        metadata,
        Column("event_id", Uuid(as_uuid=True), nullable=False),
        Column("type", String(200), nullable=False),
        Column("source", String(100), nullable=False),
        Column("publisher", String(64), nullable=False),
        Column("subject", String(200), nullable=True),
        Column("correlation_id", String(128), nullable=False),
        Column("envelope", JSONB, nullable=False),
        Column("status", String(16), nullable=False),
        Column("attempts", Integer, nullable=False),
        Column("error", Text, nullable=True),
        _ts("next_attempt_at", True),
        _ts("received_at", False),
        _ts("processed_at", True),
        _ts("updated_at", False),
        PrimaryKeyConstraint("event_id", name="rt_bus_inbox_pkey"),
        Index("rt_bus_inbox_status_idx", "status", "received_at"),
    )
    state = Table(
        sql.STATE,
        metadata,
        Column("id", BigInteger, Identity(always=False), nullable=False),
        Column("subscriber", String(64), nullable=False),
        Column("consecutive_failures", Integer, nullable=False),
        _ts("paused_until", True),
        _ts("last_failure_at", True),
        _ts("last_success_at", True),
        Column("last_error", Text, nullable=True),
        _ts("updated_at", False),
        PrimaryKeyConstraint("id", name="rt_bus_subscriber_state_pkey"),
        UniqueConstraint("subscriber", name="rt_bus_subscriber_state_uniq"),
    )
    return BusTables(outbox, delivery, inbox, state)
