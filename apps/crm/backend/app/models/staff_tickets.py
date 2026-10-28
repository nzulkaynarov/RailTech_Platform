"""Обращения сотрудников к администратору и уведомления сотрудникам (W15-H7, ADR-0015)."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TICKET_SUBJECTS = ("access", "notification", "template", "error", "other")
TICKET_STATUSES = ("new", "in_progress", "resolved")
NOTIFICATION_TABS = ("decisions", "clients", "system")


class StaffTicket(Base):
    """Обращение сотрудника: тема из списка, текст, страница и роль на момент написания."""

    __tablename__ = "staff_tickets"
    __table_args__ = (
        CheckConstraint(
            "subject IN ('access', 'notification', 'template', 'error', 'other')", name="subject"
        ),
        CheckConstraint("status IN ('new', 'in_progress', 'resolved')", name="status"),
        Index("ix_staff_tickets_author_id", "author_id", "created_at"),
        Index("ix_staff_tickets_status", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    page: Mapped[str | None] = mapped_column(String(300))
    author_role: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StaffTicketMessage(Base):
    """Ответ администратора (или пометка автора) в обращении; первое сообщение — сам `body`."""

    __tablename__ = "staff_ticket_messages"
    __table_args__ = (Index("ix_staff_ticket_messages_ticket_id", "ticket_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("staff_tickets.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StaffNotification(Base):
    """Уведомление сотруднику от CRM для колокольчика Платформы (ответ на обращение и др.).

    Общий механизм «события CRM → колокольчик» (platform-bff.md §4): тип, вкладка, текст и ссылка
    на объект (`object_kind` + `object_id`); адрес экрана строит BFF.
    """

    __tablename__ = "staff_notifications"
    __table_args__ = (
        CheckConstraint("tab IN ('decisions', 'clients', 'system')", name="tab"),
        Index("ix_staff_notifications_user_id", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    tab: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str | None] = mapped_column(String(200))
    object_kind: Mapped[str | None] = mapped_column(String(20))
    object_id: Mapped[str | None] = mapped_column(String(40))
    object_number: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
