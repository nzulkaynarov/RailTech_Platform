"""Центр внешних сервисов (M3-CRM-12, ADR-0024): проверки, инциденты, выключатели.

`external_service_checks` — строка на проверку сервиса (раз в минуту дешёвые, раз в 15 мин тяжёлые),
хранится 8 дней. `external_service_incidents` — период `fail` сервиса и отметки оповещений.
`external_service_switches` — выключатель, выставленный админом (строка есть, пока сервис трогали).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

STATUSES = ("ok", "warn", "fail", "unknown", "off")
_STATUS_CHECK = "status IN ('ok', 'warn', 'fail', 'unknown', 'off')"


class ExternalServiceCheck(Base):
    __tablename__ = "external_service_checks"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="status"),
        CheckConstraint("tier IN ('cheap', 'heavy', 'manual')", name="tier"),
        Index("ix_external_service_checks_service_at", "service_key", "checked_at"),
        Index("ix_external_service_checks_checked_at", "checked_at"),
        # W15-H3: последняя `ok` / не-`fail` проверка сервиса — «с какого времени» и полоса `fail`.
        Index(
            "ix_external_service_checks_ok_at",
            "service_key",
            "checked_at",
            postgresql_where=text("status = 'ok'"),
        ),
        Index(
            "ix_external_service_checks_notok_at",
            "service_key",
            "checked_at",
            postgresql_where=text("status <> 'ok'"),
        ),
        Index(
            "ix_external_service_checks_notfail_at",
            "service_key",
            "checked_at",
            postgresql_where=text("status <> 'fail'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    service_key: Mapped[str] = mapped_column(String(64), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tier: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    hint: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class ExternalServiceIncident(Base):
    __tablename__ = "external_service_incidents"
    __table_args__ = (
        Index("ix_external_service_incidents_service_started", "service_key", "started_at"),
        # Один открытый инцидент на сервис.
        Index(
            "uq_external_service_incidents_open",
            "service_key",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    service_key: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalCauseAlert(Base):
    """Эпизод «Сломано» по причине (общий корень сервисов) и отметки оповещений (W15-H3)."""

    __tablename__ = "external_cause_alerts"
    __table_args__ = (
        Index("ix_external_cause_alerts_cause_started", "cause_key", "started_at"),
        # Одна открытая запись на причину — дедупликация оповещений переживает рестарт процесса.
        Index(
            "uq_external_cause_alerts_open",
            "cause_key",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    cause_key: Mapped[str] = mapped_column(String(96), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Повторный сбой той же причины за сутки: сообщения не было — «нестабильно» видно в «Здоровье».
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    service_keys: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class ExternalServiceSwitch(Base):
    __tablename__ = "external_service_switches"

    service_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    # Что применено во внешней системе (перенаправленные алиасы, заблокированные deployment).
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    changed_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
