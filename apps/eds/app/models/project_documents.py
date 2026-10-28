"""Документы проектов из ERP — проекция для реестра «Все документы» (D2-5, SPEC-v3 §7.3, ADR-0015).

Договор, счёт и акт живут в ERP (владелец полей — ERP): EDS получает их события шины (`erp.contract.status_changed`,
`erp.invoice.*`, `erp.act.*`) и хранит строку на документ, чтобы реестр показывал их рядом с письмами, КП и служебными.
Общих таблиц нет, ключ — пара `(kind, erp_id)`; более старое событие не перезаписывает более новое (`updated_at` — время
события). Статусы — слова SPEC-v3 §2.4, а не коды ERP.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

PROJECT_DOCUMENT_KINDS = ("contract", "invoice", "act")


class ProjectDocument(Base):
    __tablename__ = "project_documents"
    __table_args__ = (
        CheckConstraint("kind IN ('contract', 'invoice', 'act')", name="kind"),
        UniqueConstraint("kind", "erp_id", name="uq_project_documents_kind_erp_id"),
        Index("ix_project_documents_registered_at_id", "registered_at", "id"),
        Index("ix_project_documents_erp_deal_id", "erp_deal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    erp_id: Mapped[int] = mapped_column(BigInteger)
    number: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(24))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    erp_deal_id: Mapped[int] = mapped_column(BigInteger)
    deal_number: Mapped[str | None] = mapped_column(String(64))
    erp_company_id: Mapped[int | None] = mapped_column(BigInteger)
    crm_client_id: Mapped[int | None] = mapped_column(BigInteger)
    client_name: Mapped[str | None] = mapped_column(String(255))
    client_inn: Mapped[str | None] = mapped_column(String(14))
    responsible_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
