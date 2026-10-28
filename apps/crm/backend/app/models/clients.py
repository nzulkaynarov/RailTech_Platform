"""Клиенты, документы клиентов, журнал доступа, сервисные запросы (SPEC §5.2, §5.6)."""

from datetime import date, datetime
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

DOC_TYPES: Final = "'contract','proposal','letter','invoice','act','other'"
# Поиск по документам клиента: заголовок и номер весомее текста.
DOC_TSV: Final = (
    "setweight(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(number, '')), 'A') || "
    "setweight(to_tsvector('russian', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('russian', left(coalesce(extracted_text, ''), 200000)), 'C')"
)


class Client(TimestampMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint(
            "erp_handoff_status IS NULL OR erp_handoff_status IN ('pending', 'done', 'failed')",
            name="erp_handoff_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    inn: Mapped[str | None] = mapped_column(String(32))
    segment: Mapped[str | None] = mapped_column(String(64))
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    notes: Mapped[str | None] = mapped_column(Text)
    erp_company_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # Передача в бэк-офис идёт задачей после коммита клиента (FIX-31): состояние для карточки.
    # `NULL` — передачи не было (режим local или клиент создан вручную).
    erp_handoff_status: Mapped[str | None] = mapped_column(String(16))
    erp_handoff_error: Mapped[str | None] = mapped_column(String(500))
    # Заявку в ERP ещё предстоит завести: не теряется при повторе после сбоя.
    erp_handoff_request: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"type IN ({DOC_TYPES})", name="type"),
        CheckConstraint(
            "extract_status IN ('pending', 'done', 'failed', 'skipped')", name="extract_status"
        ),
        Index("ix_documents_client_id_doc_date", "client_id", "doc_date"),
        Index("ix_documents_tsv", "tsv", postgresql_using="gin"),
        # Один выпущенный документ ERP — одна строка индекса клиента (upsert по
        # `document.created`, FIX-35, Q-FIX38-1).
        Index(
            "uq_documents_client_erp_document",
            "client_id",
            "erp_document_id",
            unique=True,
            postgresql_where=sql("erp_document_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(500))
    number: Mapped[str | None] = mapped_column(String(64))
    doc_date: Mapped[date | None] = mapped_column(Date)
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extract_status: Mapped[str] = mapped_column(String(16), server_default=sql("'pending'"))
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(DOC_TSV, persisted=True))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_visible_to_client: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    # Непрозрачный идентификатор выпущенного документа в ERP (`document.created`, id документа
    # портала); у загруженных менеджером документов его нет.
    erp_document_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class DocumentAccessLog(Base):
    __tablename__ = "document_access_log"
    __table_args__ = (
        CheckConstraint("accessed_by_type IN ('bot', 'user')", name="accessed_by_type"),
        Index("ix_document_access_log_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    accessed_by_type: Mapped[str] = mapped_column(String(8))
    accessed_by_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServiceRequest(TimestampMixin, Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'closed')", name="status"),
        Index("ix_service_requests_client_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), server_default=sql("'open'"))
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolution: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClientContact(TimestampMixin, Base):
    """Контактное лицо клиента (Q-011); основной — не более одного на клиента."""

    __tablename__ = "client_contacts"
    __table_args__ = (
        CheckConstraint(
            "preferred_channel IS NULL OR preferred_channel IN ('telegram', 'email', 'both')",
            name="preferred_channel",
        ),
        Index("ix_client_contacts_client_id", "client_id"),
        Index(
            "uq_client_contacts_primary",
            "client_id",
            unique=True,
            postgresql_where=sql("is_primary"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(255))
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    telegram_identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_identities.id", ondelete="SET NULL")
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    note: Mapped[str | None] = mapped_column(Text)
    # Предпочитаемый канал связи и приглашения в кабинет (D1-9): `telegram` | `email` | `both`; NULL
    # — по тому, что есть.
    preferred_channel: Mapped[str | None] = mapped_column(String(8))
