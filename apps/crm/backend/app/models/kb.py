"""База знаний: продукты, документы, чанки, пробелы (SPEC §5.5; ADR-0004, ADR-0007)."""

from typing import Final

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.embedding_profile import ACTIVE_PROFILE
from app.models.base import Base, TimestampMixin

EMBEDDING_DIMENSIONS: Final = ACTIVE_PROFILE.dimensions

# GENERATED-выражение tsv: `simple` для всех + стемминг по языку документа (ADR-0007).
TSV_EXPRESSION: Final = (
    "to_tsvector('simple'::regconfig, coalesce(heading_path, '') || ' ' || content) || "
    "to_tsvector(CASE language WHEN 'ru' THEN 'russian'::regconfig "
    "WHEN 'en' THEN 'english'::regconfig ELSE 'simple'::regconfig END, "
    "coalesce(heading_path, '') || ' ' || content)"
)


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class KbDocument(TimestampMixin, Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        CheckConstraint("language IN ('ru', 'uz', 'en')", name="language"),
        CheckConstraint("source_type IN ('file', 'url', 'manual')", name="source_type"),
        CheckConstraint(
            "ingest_status IN ('pending', 'processing', 'done', 'failed')", name="ingest_status"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    product_key: Mapped[str | None] = mapped_column(ForeignKey("products.key", ondelete="SET NULL"))
    language: Mapped[str] = mapped_column(String(2))
    source_type: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    mime: Mapped[str | None] = mapped_column(String(255))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    indexed_version: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger)
    ingest_status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    ingest_error: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    chunks: Mapped[list["KbChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class KbChunk(TimestampMixin, Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index(
            "ix_kb_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_kb_chunks_document_position", "document_id", "position", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(2))
    heading_path: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(TSV_EXPRESSION, persisted=True))
    position: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer)

    document: Mapped[KbDocument] = relationship(back_populates="chunks")


class KbGap(TimestampMixin, Base):
    __tablename__ = "kb_gaps"
    __table_args__ = (
        Index("ix_kb_gaps_status", "status"),
        CheckConstraint("status IN ('open', 'resolved', 'ignored')", name="status"),
        CheckConstraint("language IN ('ru', 'uz', 'en')", name="language"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text)
    question_normalized: Mapped[str] = mapped_column(Text, unique=True)
    language: Mapped[str] = mapped_column(String(2))
    best_score: Mapped[float | None] = mapped_column(Float)
    occurrences: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'open'"))
    resolved_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="SET NULL")
    )
    resolved_by: Mapped[int | None] = mapped_column(BigInteger)
