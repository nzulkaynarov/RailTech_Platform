"""Документы EDS: служебная записка, заявление, отчёт, исходящее письмо (SPEC-v3 §3.2, §10.4 `ServiceMemo`)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Document(Base):
    """Документ реестра. Номер СЗ/ЗЯ/ОТ — при создании, `ИСХ-NNN/ГГ` у письма — при отправке (до того `NULL`)."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("kind IN ('memo', 'application', 'report', 'letter_out')", name="kind"),
        CheckConstraint(
            "status IN ('draft', 'on_approval', 'returned', 'rejected', 'approved', 'to_accountant', 'paid', 'sent')",
            name="status",
        ),
        Index("ix_documents_created_at_id", "created_at", "id"),
        Index("ix_documents_author", "author_crm_user_id"),
        Index("ix_documents_erp_deal_id", "erp_deal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    number: Mapped[str | None] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    subject: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    author_crm_user_id: Mapped[int] = mapped_column(BigInteger)
    addressee_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)  # None — директор
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    due_date: Mapped[date | None] = mapped_column(Date)
    source_message_id: Mapped[str | None] = mapped_column(String(128))
    erp_deal_id: Mapped[int | None] = mapped_column(BigInteger)
    deal_number: Mapped[str | None] = mapped_column(String(64))
    recipient_name: Mapped[str | None] = mapped_column(String(255))
    recipient_inn: Mapped[str | None] = mapped_column(String(14))
    in_reply_to: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("letters.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(Base):
    """Снимок тела документа на момент отправки на согласование: новая версия после возврата не затирает прежнюю."""

    __tablename__ = "document_versions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
