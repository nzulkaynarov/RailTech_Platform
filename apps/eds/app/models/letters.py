"""Входящие письма и резолюции (SPEC-v3 §2.4, §7.3, §10.4 `Letter`, `Resolution`)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# P8b: путь делопроизводства — «На исполнении», «Исполнено», «Принято к сведению» (SPEC-v3 §3.2a).
LETTER_STATUSES = ("awaiting_resolution", "resolved", "returned", "rejected", "in_execution", "executed", "noted")
RESOLUTION_KINDS = ("execute", "reply", "info")


class Letter(Base):
    """Входящее письмо с номером `ВХ-NNN/ГГ`. Резолюция хранится в самом письме: она одна и конечна (`resolved`)."""

    __tablename__ = "letters"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_resolution', 'resolved', 'returned', 'rejected', "
            "'in_execution', 'executed', 'noted')",
            name="status",
        ),
        CheckConstraint(
            "resolution_kind IS NULL OR resolution_kind IN ('execute', 'reply', 'info')", name="resolution_kind"
        ),
        Index("ix_letters_on_control", "on_control", postgresql_where=text("on_control")),
        Index(
            "uq_letters_erp_request_id",
            "erp_request_id",
            unique=True,
            postgresql_where=text("erp_request_id IS NOT NULL"),
        ),
        Index("ix_letters_erp_deal_id", "erp_deal_id"),
        Index("ix_letters_registered_at_id", "registered_at", "id"),
        Index("ix_letters_status", "status"),
        # Проверка дубля при регистрации (P8): корреспондент + исх. № отправителя.
        Index(
            "ix_letters_sender_ref_number",
            "sender_ref_number",
            postgresql_where=text("sender_ref_number IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(24))
    subject: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    sender_inn: Mapped[str | None] = mapped_column(String(14))
    sender_contact: Mapped[str | None] = mapped_column(String(255))
    sender_ref_number: Mapped[str | None] = mapped_column(String(64))
    sender_ref_date: Mapped[date | None] = mapped_column(Date)
    received_at: Mapped[date] = mapped_column(Date)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    registered_by: Mapped[int | None] = mapped_column(BigInteger)  # None — система (по заявке ERP)
    addressee_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)  # None — директор
    manager_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    erp_request_id: Mapped[int | None] = mapped_column(BigInteger)
    erp_deal_id: Mapped[int | None] = mapped_column(BigInteger)
    deal_number: Mapped[str | None] = mapped_column(String(64))
    crm_client_id: Mapped[int | None] = mapped_column(BigInteger)
    erp_company_id: Mapped[int | None] = mapped_column(BigInteger)
    return_comment: Mapped[str | None] = mapped_column(Text)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    resolution_text: Mapped[str | None] = mapped_column(Text)
    resolution_assignees: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    resolution_due: Mapped[date | None] = mapped_column(Date)
    resolution_min_margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    resolution_decided_by: Mapped[int | None] = mapped_column(BigInteger)
    resolution_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Карточка делопроизводства (SPEC-v3 §3.2a п. 1, P8); у писем по заявке ERP — пусто.
    doc_kind: Mapped[str | None] = mapped_column(String(32))  # код справочника `letter-kinds` (EDS-REG)
    receipt_method: Mapped[str | None] = mapped_column(String(32))  # код справочника `receipt-methods` (EDS-REG)
    signed_by: Mapped[str | None] = mapped_column(String(255))
    document_due: Mapped[date | None] = mapped_column(Date)  # срок по документу (у отправителя)
    related_letter_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("letters.id", ondelete="SET NULL")
    )  # предыдущий ВХ
    related_document_id: Mapped[uuid.UUID | None] = mapped_column(
        # `documents.in_reply_to` ссылается на письма: внешний ключ отдельным ALTER, без цикла при сортировке таблиц
        Uuid,
        ForeignKey("documents.id", ondelete="SET NULL", use_alter=True),
    )  # наш ИСХ
    # Путь делопроизводства (P8b, SPEC-v3 §3.2a п. 2–5): тип резолюции, «на контроле», проект делопроизводителя, когда
    # исполнены все поручения. Резолюция пути `office` — `resolution_kind`, `resolution_text`, `resolution_due` (срок
    # ответственного), `resolution_decided_*`; люди — строки `instructions` и `letter_acquaintances`.
    resolution_kind: Mapped[str | None] = mapped_column(String(16))
    on_control: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # {kind, responsible, due, text, co_executors, acquaint, by, at} — проект резолюции делопроизводителя
    resolution_draft: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
