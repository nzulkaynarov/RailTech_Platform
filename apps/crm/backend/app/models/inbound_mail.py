"""Входящая почта общего ящика (W18A-P2, B-INB-5): письма очереди и состояние опроса.

`inbound_mail` — одно письмо (UNIQUE `message_id` — дедупликация: повторный опрос, копия письма в
ящике, смена UIDVALIDITY дубля не дают). Тело — только текст; вложения из белого списка — в бакете
вложений CRM (`attachments`: имя, тип, размер, ключ хранилища), отброшенные — `skipped` с причиной.
Состояния (W18A-P2-3; домен — `domain/inbound_mail_flow.py`): `new` → `in_work` (исполнитель
`assignee_id`, с `assigned_at`) → `registering` (ВХ создаётся в EDS, `registering_at`) → `done` с
итогом `outcome` (`registered` — по событию `eds.letter.registered`, `lead`, `replied` — ответ
отправлен, `archived` — с причиной; кто и когда — `handled_by`, `handled_at`). `spam` — из
спам-папки («Подозрительные», W18A-P2-2; «Не спам» → `new`, «Убрать» → `done/archived`). Подсказка
помощника — `assist_*`: тип, суть и предложенное действие; ничего сама не делает.

Цепочка: ответ клиента (по `In-Reply-To`/`References`) — строка с `thread_root_id`, в списке её нет;
запись-корень получает `activity_at` и, если была разобрана, снова `new` с `thread_reply`.
Адресаты: «Кому» (`to_addrs`) и копия (`cc_addrs`) раздельно; сотрудники из них — `to_staff_ids` /
`cc_staff_ids`; `personal` — «адресовано лично» (исполнитель — первый сотрудник в «Кому»).
`inbound_mail_read` — «прочитано» на человека.

`from_history` — письмо из «Загрузить письма за период» старше окна задач: в списке, не в «Моих
задачах».

`inbound_mailbox` — что уже забрано из папки: UIDVALIDITY и последний UID (на сервере письма не
помечаются), итог последнего опроса — для строки здоровья «Подключений»; строка на каждую папку.

`inbound_mail_import` — загрузка истории (W18A-P2-2): период, ход (найдено, разобрано, новых), итог.
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
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

MAIL_STATUSES = ("new", "in_work", "registering", "done", "spam")
MAIL_OUTCOMES = ("registered", "lead", "replied", "archived")
IMPORT_STATUSES = ("running", "done", "error")
ASSIST_STATUSES = ("none", "done", "unavailable")


class InboundMail(TimestampMixin, Base):
    __tablename__ = "inbound_mail"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'in_work', 'registering', 'done', 'spam')", name="status"
        ),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('registered', 'lead', 'replied', 'archived')",
            name="outcome",
        ),
        CheckConstraint("assist_status IN ('none', 'done', 'unavailable')", name="assist_status"),
        Index("uq_inbound_mail_message_id", "message_id", unique=True),
        Index("ix_inbound_mail_status_activity", "status", "activity_at"),
        Index("ix_inbound_mail_assignee_status", "assignee_id", "status"),
        Index("ix_inbound_mail_thread_root", "thread_root_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(500), nullable=False)
    mailbox: Mapped[str] = mapped_column(String(200), nullable=False)
    uidvalidity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_email: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    from_name: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    to_addrs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    subject: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    in_reply_to: Mapped[str | None] = mapped_column(Text)
    references: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    skipped: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    too_large: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # Связка с известными: клиент по адресу контакта или ИНН в тексте, открытый лид по адресу.
    client_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("clients.id", ondelete="SET NULL")
    )
    matched_lead_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="SET NULL")
    )
    inns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="new")
    from_history: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # Подсказка — только по кнопке «Подсказать» (юрист 2026-11-02): `none` — не запрашивали.
    assist_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    assist_kind: Mapped[str | None] = mapped_column(String(16))
    assist_summary: Mapped[str | None] = mapped_column(String(300))
    assist_action: Mapped[str | None] = mapped_column(String(16))
    assist_trace_id: Mapped[str | None] = mapped_column(String(64))  # трасса Langfuse для оценки
    # Итог: ВХ в EDS (номер — из события EDS), лид, причина архива; кто и когда.
    eds_letter_id: Mapped[str | None] = mapped_column(String(64))
    eds_letter_number: Mapped[str | None] = mapped_column(String(32))
    lead_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="SET NULL")
    )
    archive_reason: Mapped[str | None] = mapped_column(String(500))
    handled_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(16))
    # «В работе у …» (Help Scout «assigned to»): кто и с какого времени; `registering_at` — ВХ
    # создаётся.
    assignee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registering_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Цепочка: корень записи (NULL — это сама запись списка) и «Новое (ответ в цепочке)».
    thread_root_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inbound_mail.id", ondelete="CASCADE")
    )
    thread_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cc_addrs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    to_staff_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, server_default="[]")
    cc_staff_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, server_default="[]")
    personal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # Письмо в цепочке от адреса, которого в ней не было («новый участник переписки», W18A-P2-3).
    new_participant: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())


class InboundMailRead(Base):
    """«Прочитано» на человека: письмо непрочитано, пока нет отметки или она старше
    `activity_at`."""

    __tablename__ = "inbound_mail_read"

    mail_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("inbound_mail.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InboundMailbox(Base):
    __tablename__ = "inbound_mailbox"

    mailbox: Mapped[str] = mapped_column(String(200), primary_key=True)
    host: Mapped[str] = mapped_column(String(253), nullable=False, server_default="")
    uidvalidity: Mapped[int | None] = mapped_column(BigInteger)
    last_uid: Mapped[int | None] = mapped_column(BigInteger)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_kind: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(String(200))
    fetched_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class InboundMailImport(TimestampMixin, Base):
    __tablename__ = "inbound_mail_import"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'done', 'error')", name="status"),
        CheckConstraint("days BETWEEN 1 AND 366", name="days"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="running")
    found: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    limited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    error_kind: Mapped[str | None] = mapped_column(String(32))
    requested_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
