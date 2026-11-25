"""Подключения из интерфейса админа (аудит 2026-10-12): секреты интеграций и найденные каналы."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Uuid,
    func,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


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


class TelegramGroup(TimestampMixin, Base):
    """Группа Telegram с секретарём (ADR-0032): ждёт привязки, привязана к клиенту или отключена.

    Запись заводит бот, когда его сделали администратором группы; сообщения пишутся только в
    `bound` (`services/telegram_groups.py`). Беседа группы — `conversations.channel = 'group'`.
    """

    __tablename__ = "telegram_groups"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'bound', 'unbound', 'removed')", name="status"),
        CheckConstraint("topic_mode IN ('none', 'request')", name="topic_mode"),
        CheckConstraint("language IS NULL OR language IN ('ru', 'uz', 'en')", name="language"),
        CheckConstraint("status <> 'bound' OR client_id IS NOT NULL", name="bound_has_client"),
        Index("ix_telegram_groups_client_id", "client_id"),
    )

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    chat_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # pending — ждёт код; bound — пишем; unbound — отключили в Платформе; removed — бота убрали.
    status: Mapped[str] = mapped_column(String(10), server_default=sql("'pending'"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    # Одноразовый код привязки: бот пишет его в группу, сотрудник вводит в Платформе.
    connect_code: Mapped[str | None] = mapped_column(String(12), unique=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Последнее известное состояние бота: читает ли он всё и может ли закрепить (`my_chat_member`).
    bot_is_admin: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    can_pin: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    # Тема на заявку — настройка ТГ-2 (в ТГ-1 только хранится): none | request.
    topic_mode: Mapped[str] = mapped_column(String(8), server_default=sql("'request'"))
    language: Mapped[str | None] = mapped_column(String(2))
    notice_message_id: Mapped[int | None] = mapped_column(BigInteger)
    notice_pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bound_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ErpEventNotice(Base):
    """Сообщения в Telegram по входящему событию ERP (B4: шина rt_bus, CONTRACTS §9).

    Обработчик `uz.railtech.erp.*.v1` считает сообщения в транзакции inbox и кладёт их сюда; уходят
    они ПОСЛЕ коммита (откат или автоповтор обработчика не задваивает сообщения), задачей очереди и
    сборщиком: сообщение не теряется при падении воркера, а уже отправленным адресатам (`sent`)
    повторно не уходит. Ключ — id события шины; кода акцепта здесь нет (он идёт inline, мимо БД).
    """

    __tablename__ = "erp_event_notices"
    __table_args__ = (
        Index(
            "ix_erp_event_notices_pending",
            "created_at",
            postgresql_where=sql("notified_at IS NULL"),
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    # [{"kind": "client", "client_id", "text", "buttons"} | {"kind": "staff", "user_id", "text"}].
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # Адресаты, которым сообщение уже ушло: "<номер сообщения>:<tg_user_id>".
    sent: Mapped[list[str]] = mapped_column(
        JSONB, server_default=sql("'[]'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Все адресаты обслужены (или отправка больше не нужна: старше суток, у адресата нет Telegram).
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Аренда на время отправки: задача после обработки и сборщик не шлют одно сообщение вдвоём.
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
