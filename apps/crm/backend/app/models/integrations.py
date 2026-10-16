"""Подключения из интерфейса админа (аудит 2026-10-12): секреты интеграций и найденные каналы."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IntegrationSecret(Base):
    """Секрет интеграции, зашифрованный ключом `SECRETS_KEY` (Fernet); открытого текста нет."""

    __tablename__ = "integration_secrets"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TelegramChatCandidate(Base):
    """Канал/группа, куда бота добавили администратором (`my_chat_member`)."""

    __tablename__ = "telegram_chat_candidates"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    chat_type: Mapped[str] = mapped_column(String(16), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ErpIncomingEvent(Base):
    """Входящие вебхуки событий ERP (M3-CRM-04, CONTRACTS §3, ADR-0022).

    Идемпотентность — по `event_id` (UUID). Повторный запрос с тем же `event_id` отдаёт 200 OK
    без повторной обработки.
    """

    __tablename__ = "erp_incoming_events"
    __table_args__ = (
        CheckConstraint("status IN ('received', 'processed', 'failed')", name="status"),
        Index("ix_erp_incoming_events_crm_client_id", "crm_client_id"),
        Index("ix_erp_incoming_events_status", "status"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    erp_company_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    crm_client_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), server_default=sql("'received'"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
