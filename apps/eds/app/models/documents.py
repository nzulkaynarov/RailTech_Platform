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
    text,
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
        Index("ix_documents_signed_by", "signed_by_crm_user_id"),
        Index(
            "uq_documents_verification_code",
            "verification_code",
            unique=True,
            postgresql_where=text("verification_code IS NOT NULL"),
        ),
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
    # Пункт 1.6 плана: согласующие, которых автор добавил перед шагами шаблона (по порядку), и получатели копии — они
    # видят документ, но не решают. Списки `crm_user_id`.
    extra_approvers: Mapped[list[int]] = mapped_column(JSONB, default=list, server_default="[]")
    watchers: Mapped[list[int]] = mapped_column(JSONB, default=list, server_default="[]")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    due_date: Mapped[date | None] = mapped_column(Date)
    source_message_id: Mapped[str | None] = mapped_column(String(128))
    erp_deal_id: Mapped[int | None] = mapped_column(BigInteger)
    deal_number: Mapped[str | None] = mapped_column(String(64))
    recipient_name: Mapped[str | None] = mapped_column(String(255))
    recipient_inn: Mapped[str | None] = mapped_column(String(14))
    in_reply_to: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("letters.id"))
    # Письмо на бланке (P4): тело блоками (контракт documents/body.schema.json), «кому», почта, подписант; когда
    # зарегистрировано (дата итогового PDF); последний запрошенный PDF; передача на регистрацию исполнителем (B-P8B-4).
    body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recipient_attention: Mapped[str | None] = mapped_column(String(300))
    recipient_email: Mapped[str | None] = mapped_column(String(254))
    signatory_name: Mapped[str | None] = mapped_column(String(255))
    signatory_position: Mapped[str | None] = mapped_column(String(255))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pdf_hash: Mapped[str | None] = mapped_column(String(64), ForeignKey("document_renders.hash", use_alter=True))
    registration_requested_by: Mapped[int | None] = mapped_column(BigInteger)
    registration_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Подписание уполномоченным лицом из реестра полномочий (SIGN-3, ADR-0024 п. 1–5):
    signed_by_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signing_authority_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("signing_authorities.id", ondelete="SET NULL", use_alter=True)
    )
    signatory_basis: Mapped[str | None] = mapped_column(String(24))
    signatory_basis_text: Mapped[str | None] = mapped_column(Text)
    acting_for_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)
    verification_code: Mapped[str | None] = mapped_column(String(32))
    dispatch_method: Mapped[str | None] = mapped_column(String(16))
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


class DocumentPayment(Base):
    """Оплата согласованной служебной записки (SPEC-v3 §2.4 «Оплачена», §3.2 п. 5): дата, сумма, платёжка бухгалтера.

    Ровно одна на документ: маршрут «директор → бухгалтер» закрывается этой оплатой. Деньги живут вне EDS — здесь факт,
    который подтвердил бухгалтер, и файл платёжного поручения (счёт поставщика приложен к самой записке).
    """

    __tablename__ = "document_payments"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    paid_on: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    receipt_file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("files.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(500))
    paid_by_crm_user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
