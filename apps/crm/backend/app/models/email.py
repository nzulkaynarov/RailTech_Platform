"""Журнал писем сотрудникам (M3-CRM-08): кому, тема, шаблон, статус, ошибка.

Тело письма (временный пароль!) хранится только до отправки и только шифртекстом (Fernet,
`SECRETS_KEY`); после отправки или окончательного сбоя — стирается. Статусы:
`queued` → `sent` | `failed`; `skipped_no_smtp` — коннектор не настроен, письмо не ставилось.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

EMAIL_STATUSES = ("queued", "sent", "failed", "skipped_no_smtp")


class EmailLog(TimestampMixin, Base):
    __tablename__ = "email_log"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'sent', 'failed', 'skipped_no_smtp')", name="status"),
        Index("ix_email_log_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
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
