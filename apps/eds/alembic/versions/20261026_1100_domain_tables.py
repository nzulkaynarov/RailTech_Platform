"""Домен EDS: счётчики номеров, письма, документы, маршруты согласования, журнал, файлы, идемпотентность

Волна 12, E3 (docs/runbooks/wave12-eds-c1.md §2): реестр и нумерация (`number_counters`), входящие письма с резолюциями
(`letters`), документы и их версии (`documents`, `document_versions`), маршруты и шаги (`approval_routes`,
`approval_steps`), журнал (`journal`), файлы с версиями (`files`, `file_versions`), ключи `Idempotency-Key`.

Revision ID: 0004_domain
Revises: 0003_employees_sso_jti
Create Date: 2026-10-26 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_domain"
down_revision: str | Sequence[str] | None = "0003_employees_sso_jti"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("crm_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", "crm_user_id", "scope", name=op.f("pk_idempotency_keys")),
    )
    op.create_index(op.f("ix_idempotency_keys_created_at"), "idempotency_keys", ["created_at"], unique=False)
    op.create_table(
        "letters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("sender_inn", sa.String(length=14), nullable=True),
        sa.Column("sender_ref_number", sa.String(length=64), nullable=True),
        sa.Column("sender_ref_date", sa.Date(), nullable=True),
        sa.Column("received_at", sa.Date(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_by", sa.BigInteger(), nullable=True),
        sa.Column("addressee_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("manager_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("urgent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("erp_request_id", sa.BigInteger(), nullable=True),
        sa.Column("erp_deal_id", sa.BigInteger(), nullable=True),
        sa.Column("deal_number", sa.String(length=64), nullable=True),
        sa.Column("crm_client_id", sa.BigInteger(), nullable=True),
        sa.Column("erp_company_id", sa.BigInteger(), nullable=True),
        sa.Column("return_comment", sa.Text(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("resolution_text", sa.Text(), nullable=True),
        sa.Column("resolution_assignees", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resolution_due", sa.Date(), nullable=True),
        sa.Column("resolution_min_margin_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("resolution_decided_by", sa.BigInteger(), nullable=True),
        sa.Column("resolution_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('awaiting_resolution', 'resolved', 'returned', 'rejected')", name=op.f("ck_letters_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_letters")),
        sa.UniqueConstraint("number", name=op.f("uq_letters_number")),
    )
    op.create_index("ix_letters_erp_deal_id", "letters", ["erp_deal_id"], unique=False)
    op.create_index("ix_letters_registered_at_id", "letters", ["registered_at", "id"], unique=False)
    op.create_index("ix_letters_status", "letters", ["status"], unique=False)
    op.create_index(
        "uq_letters_erp_request_id",
        "letters",
        ["erp_request_id"],
        unique=True,
        postgresql_where=sa.text("erp_request_id IS NOT NULL"),
    )
    op.create_table(
        "number_counters",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("year", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("last_value", sa.BigInteger(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("kind", "year", name=op.f("pk_number_counters")),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author_crm_user_id", sa.BigInteger(), nullable=False),
        sa.Column("addressee_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("source_message_id", sa.String(length=128), nullable=True),
        sa.Column("erp_deal_id", sa.BigInteger(), nullable=True),
        sa.Column("deal_number", sa.String(length=64), nullable=True),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("recipient_inn", sa.String(length=14), nullable=True),
        sa.Column("in_reply_to", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('memo', 'application', 'report', 'letter_out')", name=op.f("ck_documents_kind")),
        sa.CheckConstraint(
            "status IN ('draft', 'on_approval', 'returned', 'rejected', 'approved', 'to_accountant', 'paid', 'sent')",
            name=op.f("ck_documents_status"),
        ),
        sa.ForeignKeyConstraint(["in_reply_to"], ["letters.id"], name=op.f("fk_documents_in_reply_to_letters")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("number", name=op.f("uq_documents_number")),
    )
    op.create_index("ix_documents_author", "documents", ["author_crm_user_id"], unique=False)
    op.create_index("ix_documents_created_at_id", "documents", ["created_at", "id"], unique=False)
    op.create_index("ix_documents_erp_deal_id", "documents", ["erp_deal_id"], unique=False)
    op.create_table(
        "approval_routes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("round", sa.Integer(), server_default="1", nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("erp_quote_id", sa.BigInteger(), nullable=True),
        sa.Column("quote_number", sa.String(length=64), nullable=True),
        sa.Column("quote_version", sa.Integer(), nullable=True),
        sa.Column("erp_deal_id", sa.BigInteger(), nullable=True),
        sa.Column("deal_number", sa.String(length=64), nullable=True),
        sa.Column("crm_client_id", sa.BigInteger(), nullable=True),
        sa.Column("erp_company_id", sa.BigInteger(), nullable=True),
        sa.Column("eds_letter_id", sa.Uuid(), nullable=True),
        sa.Column("quote_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("outgoing_number", sa.String(length=32), nullable=True),
        sa.Column("channels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'approved', 'returned', 'rejected')", name=op.f("ck_approval_routes_status")
        ),
        sa.CheckConstraint(
            "template IN ('memo', 'application', 'report', 'quote')", name=op.f("ck_approval_routes_template")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_approval_routes_document_id_documents"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_routes")),
        sa.UniqueConstraint("document_id", "round", name="uq_approval_routes_document_round"),
        sa.UniqueConstraint("erp_quote_id", "quote_version", name="uq_approval_routes_quote_version"),
    )
    op.create_index("ix_approval_routes_created_at_id", "approval_routes", ["created_at", "id"], unique=False)
    op.create_index("ix_approval_routes_status", "approval_routes", ["status"], unique=False)
    op.create_table(
        "document_versions",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "version", name=op.f("pk_document_versions")),
    )
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("letter_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("letter_id IS NULL OR document_id IS NULL", name=op.f("ck_files_one_owner")),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_files_document_id_documents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["letter_id"], ["letters.id"], name=op.f("fk_files_letter_id_letters"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
    )
    op.create_index(op.f("ix_files_document_id"), "files", ["document_id"], unique=False)
    op.create_index(op.f("ix_files_letter_id"), "files", ["letter_id"], unique=False)
    op.create_table(
        "approval_steps",
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("index", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("assignee_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("assignee_permission", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'current', 'approved', 'returned', 'rejected', 'skipped')",
            name=op.f("ck_approval_steps_status"),
        ),
        sa.CheckConstraint(
            "(assignee_crm_user_id IS NULL) <> (assignee_permission IS NULL)",
            name=op.f("ck_approval_steps_one_assignee"),
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approval_routes.id"],
            name="fk_approval_steps_approval_id_approval_routes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("approval_id", "index", name=op.f("pk_approval_steps")),
    )
    op.create_index("ix_approval_steps_assignee", "approval_steps", ["assignee_crm_user_id"], unique=False)
    op.create_table(
        "file_versions",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("s3_key", sa.String(length=255), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_file_versions_file_id_files"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("file_id", "version", name=op.f("pk_file_versions")),
        sa.UniqueConstraint("s3_key", name=op.f("uq_file_versions_s3_key")),
    )
    op.create_table(
        "journal",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("by_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("letter_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approval_routes.id"],
            name=op.f("fk_journal_approval_id_approval_routes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name=op.f("fk_journal_document_id_documents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["letter_id"], ["letters.id"], name=op.f("fk_journal_letter_id_letters"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal")),
    )
    op.create_index("ix_journal_approval_id", "journal", ["approval_id", "id"], unique=False)
    op.create_index("ix_journal_document_id", "journal", ["document_id", "id"], unique=False)
    op.create_index("ix_journal_letter_id", "journal", ["letter_id", "id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_journal_letter_id", table_name="journal")
    op.drop_index("ix_journal_document_id", table_name="journal")
    op.drop_index("ix_journal_approval_id", table_name="journal")
    op.drop_table("journal")
    op.drop_table("file_versions")
    op.drop_index("ix_approval_steps_assignee", table_name="approval_steps")
    op.drop_table("approval_steps")
    op.drop_index(op.f("ix_files_letter_id"), table_name="files")
    op.drop_index(op.f("ix_files_document_id"), table_name="files")
    op.drop_table("files")
    op.drop_table("document_versions")
    op.drop_index("ix_approval_routes_status", table_name="approval_routes")
    op.drop_index("ix_approval_routes_created_at_id", table_name="approval_routes")
    op.drop_table("approval_routes")
    op.drop_index("ix_documents_erp_deal_id", table_name="documents")
    op.drop_index("ix_documents_created_at_id", table_name="documents")
    op.drop_index("ix_documents_author", table_name="documents")
    op.drop_table("documents")
    op.drop_table("number_counters")
    op.drop_index(
        "uq_letters_erp_request_id", table_name="letters", postgresql_where=sa.text("erp_request_id IS NOT NULL")
    )
    op.drop_index("ix_letters_status", table_name="letters")
    op.drop_index("ix_letters_registered_at_id", table_name="letters")
    op.drop_index("ix_letters_erp_deal_id", table_name="letters")
    op.drop_table("letters")
    op.drop_index(op.f("ix_idempotency_keys_created_at"), table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
