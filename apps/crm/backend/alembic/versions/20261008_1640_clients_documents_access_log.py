"""clients, documents, document_access_log, service_requests (Фаза 6)

Документы клиентов с полнотекстовым поиском; ссылки лидов и идентичностей на клиента.

Revision ID: 0007_clients
Revises: 0006_dashboard
Create Date: 2026-10-08 16:40:08.992928+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_clients"
down_revision: str | Sequence[str] | None = "0006_dashboard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPDATED_AT_TABLES = ("clients", "documents", "service_requests")
DOC_TSV = (
    "setweight(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(number, '')), 'A') || "
    "setweight(to_tsvector('russian', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('russian', left(coalesce(extracted_text, ''), 200000)), 'C')"
)


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("inn", sa.String(length=32), nullable=True),
        sa.Column("segment", sa.String(length=64), nullable=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_clients_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clients")),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "extract_status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                DOC_TSV,
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_visible_to_client", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
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
            "extract_status IN ('pending', 'done', 'failed', 'skipped')",
            name=op.f("ck_documents_extract_status"),
        ),
        sa.CheckConstraint(
            "type IN ('contract','proposal','letter','invoice','act','other')",
            name=op.f("ck_documents_type"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_documents_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_documents_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(
        "ix_documents_client_id_doc_date", "documents", ["client_id", "doc_date"], unique=False
    )
    op.create_index("ix_documents_tsv", "documents", ["tsv"], unique=False, postgresql_using="gin")
    op.create_table(
        "document_access_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("accessed_by_type", sa.String(length=8), nullable=False),
        sa.Column("accessed_by_id", sa.BigInteger(), nullable=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "accessed_by_type IN ('bot', 'user')",
            name=op.f("ck_document_access_log_accessed_by_type"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_access_log_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_access_log")),
    )
    op.create_index(
        "ix_document_access_log_document_id", "document_access_log", ["document_id"], unique=False
    )
    op.create_table(
        "service_requests",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("client_id", sa.BigInteger(), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=8), server_default=sa.text("'open'"), nullable=False),
        sa.Column("closed_by", sa.BigInteger(), nullable=True),
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
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_service_requests_status")),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name=op.f("fk_service_requests_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["closed_by"],
            ["users.id"],
            name=op.f("fk_service_requests_closed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_service_requests_lead_id_leads"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_requests")),
    )
    op.create_index(
        "ix_service_requests_client_id", "service_requests", ["client_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_leads_client_id_clients"),
        "leads",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_telegram_identities_client_id_clients"),
        "telegram_identities",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for table in UPDATED_AT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_telegram_identities_client_id_clients"), "telegram_identities", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_leads_client_id_clients"), "leads", type_="foreignkey")
    op.drop_index("ix_service_requests_client_id", table_name="service_requests")
    op.drop_table("service_requests")
    op.drop_index("ix_document_access_log_document_id", table_name="document_access_log")
    op.drop_table("document_access_log")
    op.drop_index("ix_documents_tsv", table_name="documents", postgresql_using="gin")
    op.drop_index("ix_documents_client_id_doc_date", table_name="documents")
    op.drop_table("documents")
    op.drop_table("clients")
