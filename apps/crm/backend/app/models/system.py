"""Служебные таблицы эксплуатации (SPEC §13): дедупликация системных алертов, состояние бота."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Identity,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SystemAlert(Base):
    """Состояние проверки монитора: активна ли, с какого момента и когда ушло в канал."""

    __tablename__ = "system_alerts"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detail: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LlmUsage(Base):
    """Единый учёт вызовов моделей (аудит 2026-10-12 §3 п. 5): каждый вызов — строка.

    `kind='test'` — прогоны eval/load-test (флаг окружения `LLM_USAGE_KIND`).
    """

    __tablename__ = "llm_usage"
    __table_args__ = (CheckConstraint("kind IN ('work', 'test')", name="kind"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    lead_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="work")


class BotRuntimeState(Base):
    """Единственная строка: связь `crm-api` и `crm-bot` через БД (S0-4, ADR-0017).

    Пишет `crm-bot`: что он сейчас делает (`running`, `source`, `username`, `last_error`,
    `profile`) и пульс `heartbeat_at`. Пишет `crm-api`: `restart_requested_at` — «токен сменили,
    перезапусти бота». `crm-bot` применяет запрос и ставит `restart_applied_at`.
    Токен сюда не попадает.
    """

    __tablename__ = "bot_runtime"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1, autoincrement=False)
    running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mode: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="none")
    username: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(String(160))
    # Итог последней публикации профиля бота: `ok`, `at`, `changed`, `error`, `retry_after`.
    profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restart_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restart_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IdentityCatalogState(Base):
    """Отпечаток каталога, по которому CRM последний раз опубликовала снимки сотрудников на шину.

    Одна строка на каталог (`key = 'eds_permissions'`): права EDS в `identity.user.*` меняются без
    события, когда меняется каталог `platform-rbac.yaml`; смена отпечатка = «переопубликовать»
    (`services/identity_catalog.py`). Не `settings`: та таблица валидирует ключи и отдаёт их в API.
    """

    __tablename__ = "identity_catalog_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    published_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
