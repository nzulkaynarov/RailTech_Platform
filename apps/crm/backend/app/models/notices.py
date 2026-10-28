"""Сообщения клиенту, которые отправляет система, и их итог (D1-9): подтверждение запроса с сайта,
«Заявка принята»,
приглашение в кабинет.

Строка — одно намерение «сообщить клиенту», а не одно письмо: канал выбран (`telegram` | `email` |
`both`), итог виден
менеджеру в карточке лида и клиента. Статусы: `queued` → `sent` | `failed`; `skipped` — слать некуда
или нечем (только
телефон, не настроена почта) — причина кодом в `error`, слова — `domain/notice_errors.py`. Письмо
идёт через `email_log`
(`email_log_id`), итог письма читается оттуда. Адресов и телефонов в строке нет: обезличивание лида
её не затрагивает.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

NOTICE_KINDS = ("web_confirmation", "request_accepted", "portal_invite")
NOTICE_CHANNELS = ("telegram", "email", "both", "none")
NOTICE_STATUSES = ("queued", "sent", "failed", "skipped")


class ClientNotice(TimestampMixin, Base):
    __tablename__ = "client_notices"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('web_confirmation', 'request_accepted', 'portal_invite')", name="kind"
        ),
        CheckConstraint("channel IN ('telegram', 'email', 'both', 'none')", name="channel"),
        CheckConstraint("status IN ('queued', 'sent', 'failed', 'skipped')", name="status"),
        Index("ix_client_notices_lead_id_kind", "lead_id", "kind"),
        Index("ix_client_notices_client_id_kind", "client_id", "kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("client_contacts.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(8), server_default=sql("'queued'"))
    # Код причины сбоя или пропуска (`domain/notice_errors.ERRORS`); NULL — всё хорошо.
    error: Mapped[str | None] = mapped_column(String(64))
    # Подробности канала: `sent_via` (что ушло), `telegram` / `email` — состояние каждого канала
    # приглашения.
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql("'{}'::jsonb"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=sql("0"))
    email_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_log.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Защита от дублей при повторной доставке события шины или повторном запросе: уникальный ключ.
    dedupe_key: Mapped[str | None] = mapped_column(String(128), unique=True)
