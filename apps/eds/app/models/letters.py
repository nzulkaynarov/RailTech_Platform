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

LETTER_STATUSES = ("awaiting_resolution", "resolved", "returned", "rejected")


class Letter(Base):
    """Входящее письмо с номером `ВХ-NNN/ГГ`. Резолюция хранится в самом письме: она одна и конечна (`resolved`)."""

    __tablename__ = "letters"
    __table_args__ = (
        CheckConstraint("status IN ('awaiting_resolution', 'resolved', 'returned', 'rejected')", name="status"),
        Index(
            "uq_letters_erp_request_id",
            "erp_request_id",
            unique=True,
            postgresql_where=text("erp_request_id IS NOT NULL"),
        ),
        Index("ix_letters_erp_deal_id", "erp_deal_id"),
        Index("ix_letters_registered_at_id", "registered_at", "id"),
        Index("ix_letters_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(24))
    subject: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    sender_inn: Mapped[str | None] = mapped_column(String(14))
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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
