"""Журнал доставки почты ансамбля (M3-CRM-08, W18A-P1): кому, тема, шаблон, статус, ошибка.

Почтовый сервис CRM — единственный отправитель: свои письма (сотрудникам, клиентам D1-9) и письма,
которые ERP и EDS просят отправить по шине (`uz.railtech.<домен>.mail.requested.v1`). `source` —
система-источник, `purpose` — назначение (код шаблона отправителя), `request_key` — ключ
идемпотентности отправителя (UNIQUE с `source`: повтор запроса второго письма не даёт).

Тело, HTML и ссылки на вложения хранятся только до отправки и только шифртекстом (Fernet,
`SECRETS_KEY`); после отправки или окончательного сбоя — стираются. Статусы:
`queued` → `sent` | `failed`; `skipped_no_smtp` — коннектор не настроен, письмо не ставилось.
Временная ошибка SMTP оставляет строку `queued` с причиной в `error` до следующей попытки.
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
    LargeBinary,
    String,
    Text,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

EMAIL_STATUSES = ("queued", "sent", "failed", "skipped_no_smtp")
EMAIL_SOURCES = ("crm", "erp", "eds")


class EmailLog(TimestampMixin, Base):
    __tablename__ = "email_log"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'sent', 'failed', 'skipped_no_smtp')", name="status"),
        CheckConstraint("source IN ('crm', 'erp', 'eds')", name="source"),
        Index("ix_email_log_created_at", "created_at"),
        Index(
            "uq_email_log_request",
            "source",
            "request_key",
            unique=True,
            postgresql_where=text("request_key IS NOT NULL"),
        ),
        Index(
            "ix_email_log_message_id",
            "message_id",
            postgresql_where=text("message_id IS NOT NULL"),
        ),
        Index(
            "ix_email_log_bus_event",
            "bus_event_id",
            postgresql_where=text("bus_event_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    to_email: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    lang: Mapped[str] = mapped_column(String(2), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    body_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Получатель-сотрудник и кто запросил письмо; при удалении пользователя — NULL, запись остаётся.
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Один отправитель ансамбля (W18A-P1): откуда письмо и зачем.
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="crm")
    purpose: Mapped[str | None] = mapped_column(String(64))
    request_key: Mapped[str | None] = mapped_column(String(128))
    bus_event_id: Mapped[str | None] = mapped_column(String(64))
    ref_kind: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[str | None] = mapped_column(String(64))
    reply_to: Mapped[str | None] = mapped_column(String(255))
    notify: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    html_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    links_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    #: Ближайший срок ссылок на вложения (MAIL-2): повтор письма — пока ссылки живы.
    links_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Только метаданные вложений: имя, тип, размер, sha256 (ссылки — в `links_ciphertext`).
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Ответ в ту же цепочку (W18A-P2): `In-Reply-To` и `References` письма, на которое отвечаем.
    thread_headers: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    # Message-ID of the letter as it went out (set before sending): a delivery report is linked to
    # its letter by it. Bounce facts (`bounced_at`, code, reason) show in the mail log.
    message_id: Mapped[str | None] = mapped_column(String(255))
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bounce_status: Mapped[str | None] = mapped_column(String(16))
    bounce_reason: Mapped[str | None] = mapped_column(String(32))
    bounce_message_id: Mapped[str | None] = mapped_column(String(255))


class EmailUndeliverable(TimestampMixin, Base):
    """An address that mail servers report as unreachable (delivery status notifications).

    Keyed by the lower-cased address, not by the lead or contact: the card shows the state by its
    e-mail, and editing the address in the card means a different key — the block lifts itself.
    `permanent` (5.x.x) blocks automatic mail at once; `soft` (4.x.x) counts reports and blocks
    from `SOFT_LIMIT` of them (`app/services/bounces.py`).
    """

    __tablename__ = "email_undeliverable"
    __table_args__ = (
        CheckConstraint("kind IN ('permanent', 'soft')", name="kind"),
        Index("uq_email_undeliverable_email", "email", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    reports: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    status_code: Mapped[str | None] = mapped_column(String(16))
    diagnostic: Mapped[str | None] = mapped_column(Text)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_report_id: Mapped[str | None] = mapped_column(String(255))
    email_log_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("email_log.id", ondelete="SET NULL")
    )
