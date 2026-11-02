"""Письмо на бланке (P4 волны 18a, D-DOC2 минимум): проекция бланка ERP, рендеры PDF и журнал отправки адресату.

- `letterhead` — одна строка: снимок бланка своей компании из события `erp.letterhead.updated` (владелец — ERP).
- `letterhead_logos` — логотипы по SHA-256 (неизменяемые): рендер и снимок выпущенного письма ссылаются на хеш.
- `document_renders` — PDF по хешу ввода рендера (тело, реквизиты письма, бланк, подписант): кэш и снимок выпуска
(B-094).
- `document_mailings` — «Отправить адресату» через почтовый сервис CRM: строка на попытку, итог —
`crm.mail.sent|failed`.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

RENDER_STATUSES = ("pending", "ready", "failed")
MAILING_STATUSES = ("awaiting_pdf", "requested", "sent", "failed")


class LetterheadLogo(Base):
    """Логотип бланка байтами (PNG, JPEG, WebP ≤ 512 КиБ — как `rt_docs.Logo`); ключ — SHA-256 содержимого."""

    __tablename__ = "letterhead_logos"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(32))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Letterhead(Base):
    """Бланк своей компании — проекция ERP. Строка одна (`id = 1`); более старое событие её не перезаписывает."""

    __tablename__ = "letterhead"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    erp_company_id: Mapped[int] = mapped_column(BigInteger)
    company_name: Mapped[str] = mapped_column(String(255))
    inn: Mapped[str] = mapped_column(String(20))
    legal_address: Mapped[str] = mapped_column(Text)
    bank_details: Mapped[str] = mapped_column(Text)
    signatory_name: Mapped[str] = mapped_column(String(255))
    signatory_position: Mapped[str] = mapped_column(String(255))
    footer_text: Mapped[str] = mapped_column(Text)
    accent_color: Mapped[str] = mapped_column(String(7))
    font_family: Mapped[str] = mapped_column(String(5))
    logo_sha256: Mapped[str | None] = mapped_column(String(64), ForeignKey("letterhead_logos.sha256"))
    logo_omitted: Mapped[str | None] = mapped_column(String(16))
    source_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # `time` события — порядок снимков
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentRender(Base):
    """PDF по хешу ввода. `payload` — всё, что нужно рендеру (кроме байтов логотипа): тот же ввод — тот же файл."""

    __tablename__ = "document_renders"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'ready', 'failed')", name="status"),
        Index("ix_document_renders_pending", "created_at", postgresql_where=text("status = 'pending'")),
    )

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(8))
    final: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    logo_sha256: Mapped[str | None] = mapped_column(String(64), ForeignKey("letterhead_logos.sha256"))
    storage_key: Mapped[str | None] = mapped_column(String(128))
    size: Mapped[int | None] = mapped_column(Integer)
    pages: Mapped[int | None] = mapped_column(Integer)
    last_page_fill: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # запрошен (или повторно после ошибки)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentMailing(Base):
    """Попытка «Отправить адресату»: ждёт итоговый PDF → запрос CRM (`mail.requested`) → итог CRM."""

    __tablename__ = "document_mailings"
    __table_args__ = (
        CheckConstraint("status IN ('awaiting_pdf', 'requested', 'sent', 'failed')", name="status"),
        Index("ix_document_mailings_document", "document_id", "requested_at"),
        Index("ix_document_mailings_awaiting", "render_hash", postgresql_where=text("status = 'awaiting_pdf'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"))
    request_key: Mapped[str] = mapped_column(String(128), unique=True)
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String(254)))
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    render_hash: Mapped[str] = mapped_column(String(64), ForeignKey("document_renders.hash"))
    requested_by: Mapped[int | None] = mapped_column(BigInteger)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
