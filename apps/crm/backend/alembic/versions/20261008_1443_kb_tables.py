"""kb tables: products, kb_documents, kb_chunks, kb_gaps (Фаза 1)

Также функция set_updated_at() для триггеров updated_at всех таблиц (SPEC §5).

Revision ID: 0002_kb
Revises: 0001_init
Create Date: 2026-10-08 14:43:13.660602+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_kb"
down_revision: str | Sequence[str] | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("products", "kb_documents", "kb_chunks", "kb_gaps")

SET_UPDATED_AT = """
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def _add_updated_at_triggers(tables: tuple[str, ...]) -> None:
    for table in tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def upgrade() -> None:
    op.execute(SET_UPDATED_AT)
    op.create_table(
        "products",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_products")),
    )
    op.create_table(
        "kb_documents",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("product_key", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("mime", sa.String(length=255), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("indexed_version", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "ingest_status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("ingest_error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ingest_status IN ('pending', 'processing', 'done', 'failed')",
            name=op.f("ck_kb_documents_ingest_status"),
        ),
        sa.CheckConstraint("language IN ('ru', 'uz', 'en')", name=op.f("ck_kb_documents_language")),
        sa.CheckConstraint(
            "source_type IN ('file', 'url', 'manual')", name=op.f("ck_kb_documents_source_type")
        ),
        sa.ForeignKeyConstraint(
            ["product_key"],
            ["products.key"],
            name=op.f("fk_kb_documents_product_key_products"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_documents")),
    )
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("heading_path", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, coalesce(heading_path, '') || ' ' || content) || "
                "to_tsvector(CASE language WHEN 'ru' THEN 'russian'::regconfig "
                "WHEN 'en' THEN 'english'::regconfig ELSE 'simple'::regconfig END, "
                "coalesce(heading_path, '') || ' ' || content)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["kb_documents.id"],
            name=op.f("fk_kb_chunks_document_id_kb_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_chunks")),
    )
    op.create_index(
        "ix_kb_chunks_document_position", "kb_chunks", ["document_id", "position"], unique=True
    )
    op.create_index(
        "ix_kb_chunks_embedding_hnsw",
        "kb_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_kb_chunks_tsv", "kb_chunks", ["tsv"], unique=False, postgresql_using="gin")
    op.create_table(
        "kb_gaps",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_normalized", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("best_score", sa.Float(), nullable=True),
        sa.Column("occurrences", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'open'"), nullable=False),
        sa.Column("resolved_document_id", sa.BigInteger(), nullable=True),
        sa.Column("resolved_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("language IN ('ru', 'uz', 'en')", name=op.f("ck_kb_gaps_language")),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'ignored')", name=op.f("ck_kb_gaps_status")
        ),
        sa.ForeignKeyConstraint(
            ["resolved_document_id"],
            ["kb_documents.id"],
            name=op.f("fk_kb_gaps_resolved_document_id_kb_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_gaps")),
        sa.UniqueConstraint("question_normalized", name=op.f("uq_kb_gaps_question_normalized")),
    )
    op.create_index("ix_kb_gaps_status", "kb_gaps", ["status"])
    _add_updated_at_triggers(TABLES)


def downgrade() -> None:
    op.drop_index("ix_kb_gaps_status", table_name="kb_gaps")
    op.drop_table("kb_gaps")
    op.drop_index("ix_kb_chunks_tsv", table_name="kb_chunks", postgresql_using="gin")
    op.drop_index(
        "ix_kb_chunks_embedding_hnsw",
        table_name="kb_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_kb_chunks_document_position", table_name="kb_chunks")
    op.drop_table("kb_chunks")
    op.drop_table("kb_documents")
    op.drop_table("products")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
