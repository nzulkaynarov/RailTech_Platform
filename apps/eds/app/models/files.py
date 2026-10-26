"""Файлы документов с версиями; содержимое — в S3 (`eds-private`), в базе — метаданные и контрольная сумма."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StoredFile(Base):
    """Цепочка версий файла. Привязана не больше чем к одному объекту; непривязанный видит только загрузивший."""

    __tablename__ = "files"
    __table_args__ = (CheckConstraint("letter_id IS NULL OR document_id IS NULL", name="one_owner"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    letter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("letters.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )


class FileVersion(Base):
    __tablename__ = "file_versions"

    file_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("files.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    s3_key: Mapped[str] = mapped_column(String(255), unique=True)
    uploaded_by: Mapped[int] = mapped_column(BigInteger)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
