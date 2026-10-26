"""Журнал «кто, что, когда, файл» по письму, документу и маршруту (SPEC-v3 §7.3: у каждого документа есть журнал)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class JournalEntry(Base):
    """Строка журнала. Секреты и токены сюда не попадают (CONVENTIONS.md §2 п. 7).

    Все три ссылки пусты у действий вне объекта (`registry.export`); `by_crm_user_id = NULL` — действие системы.
    """

    __tablename__ = "journal"
    __table_args__ = (
        Index("ix_journal_letter_id", "letter_id", "id"),
        Index("ix_journal_document_id", "document_id", "id"),
        Index("ix_journal_approval_id", "approval_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(String(64))
    by_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    version: Mapped[int | None] = mapped_column(Integer)
    letter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("letters.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("approval_routes.id", ondelete="CASCADE"))
