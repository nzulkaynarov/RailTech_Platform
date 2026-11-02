"""Письмо на бланке (P4 волны 18a, D-DOC2 минимум)

Проекция бланка ERP (`letterhead`, логотипы `letterhead_logos`), PDF по хешу ввода (`document_renders`, B-094), журнал
отправки адресату (`document_mailings`) и поля письма в `documents`: тело блоками, «кому», почта, подписант, дата
регистрации, последний PDF, передача на регистрацию (B-P8B-4). Downgrade удаляет таблицы и поля (письма остаются с
текстом).

Revision ID: 983e0473b753
Revises: be9417052e71
Create Date: 2026-11-02 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "983e0473b753"
down_revision: str | Sequence[str] | None = "be9417052e71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "letterhead_logos",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("sha256", name=op.f("pk_letterhead_logos")),
    )
    op.create_table(
        "letterhead",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("erp_company_id", sa.BigInteger(), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("inn", sa.String(length=20), nullable=False),
        sa.Column("legal_address", sa.Text(), nullable=False),
        sa.Column("bank_details", sa.Text(), nullable=False),
        sa.Column("signatory_name", sa.String(length=255), nullable=False),
        sa.Column("signatory_position", sa.String(length=255), nullable=False),
        sa.Column("footer_text", sa.Text(), nullable=False),
        sa.Column("accent_color", sa.String(length=7), nullable=False),
        sa.Column("font_family", sa.String(length=5), nullable=False),
        sa.Column("logo_sha256", sa.String(length=64), nullable=True),
        sa.Column("logo_omitted", sa.String(length=16), nullable=True),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_letterhead_single_row")),
        sa.ForeignKeyConstraint(
            ["logo_sha256"], ["letterhead_logos.sha256"], name=op.f("fk_letterhead_logo_sha256_letterhead_logos")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_letterhead")),
    )
    op.create_table(
        "document_renders",
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("final", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("logo_sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=128), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("last_page_fill", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name=op.f("ck_document_renders_status")),
        sa.ForeignKeyConstraint(
            ["logo_sha256"],
            ["letterhead_logos.sha256"],
            name=op.f("fk_document_renders_logo_sha256_letterhead_logos"),
        ),
        sa.PrimaryKeyConstraint("hash", name=op.f("pk_document_renders")),
    )
    op.create_index(
        "ix_document_renders_pending",
        "document_renders",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "document_mailings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("recipients", postgresql.ARRAY(sa.String(length=254)), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("render_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('awaiting_pdf', 'requested', 'sent', 'failed')", name=op.f("ck_document_mailings_status")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_mailings_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["render_hash"], ["document_renders.hash"], name=op.f("fk_document_mailings_render_hash_document_renders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_mailings")),
        sa.UniqueConstraint("request_key", name=op.f("uq_document_mailings_request_key")),
    )
    op.create_index("ix_document_mailings_document", "document_mailings", ["document_id", "requested_at"])
    op.create_index(
        "ix_document_mailings_awaiting",
        "document_mailings",
        ["render_hash"],
        postgresql_where=sa.text("status = 'awaiting_pdf'"),
    )
    op.add_column("documents", sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("documents", sa.Column("recipient_attention", sa.String(length=300), nullable=True))
    op.add_column("documents", sa.Column("recipient_email", sa.String(length=254), nullable=True))
    op.add_column("documents", sa.Column("signatory_name", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("signatory_position", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("pdf_hash", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("registration_requested_by", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("registration_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_pdf_hash_document_renders"), "documents", "document_renders", ["pdf_hash"], ["hash"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_documents_pdf_hash_document_renders"), "documents", type_="foreignkey")
    for column in (
        "registration_requested_at",
        "registration_requested_by",
        "pdf_hash",
        "registered_at",
        "signatory_position",
        "signatory_name",
        "recipient_email",
        "recipient_attention",
        "body",
    ):
        op.drop_column("documents", column)
    op.drop_index("ix_document_mailings_awaiting", table_name="document_mailings")
    op.drop_index("ix_document_mailings_document", table_name="document_mailings")
    op.drop_table("document_mailings")
    op.drop_index("ix_document_renders_pending", table_name="document_renders")
    op.drop_table("document_renders")
    op.drop_table("letterhead")
    op.drop_table("letterhead_logos")
