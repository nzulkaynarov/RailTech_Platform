"""Документы проектов из ERP: проекция для реестра «Все документы» (D2-5)

Договор, счёт и акт — владелец ERP; EDS хранит строку на документ по событиям шины, чтобы реестр показывал их рядом с
письмами, КП и служебными записками (SPEC-v3 §7.3, B-024). Общих таблиц нет; ключ — пара `(kind, erp_id)`.

Revision ID: 0008_project_documents
Revises: 0007_document_payments
Create Date: 2026-10-28 13:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_project_documents"
down_revision: str | Sequence[str] | None = "0007_document_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("erp_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("erp_deal_id", sa.BigInteger(), nullable=False),
        sa.Column("deal_number", sa.String(length=64), nullable=True),
        sa.Column("erp_company_id", sa.BigInteger(), nullable=True),
        sa.Column("crm_client_id", sa.BigInteger(), nullable=True),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("client_inn", sa.String(length=14), nullable=True),
        sa.Column("responsible_crm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('contract', 'invoice', 'act')", name=op.f("ck_project_documents_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_documents")),
        sa.UniqueConstraint("kind", "erp_id", name="uq_project_documents_kind_erp_id"),
    )
    op.create_index("ix_project_documents_registered_at_id", "project_documents", ["registered_at", "id"], unique=False)
    op.create_index("ix_project_documents_erp_deal_id", "project_documents", ["erp_deal_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_documents_erp_deal_id", table_name="project_documents")
    op.drop_index("ix_project_documents_registered_at_id", table_name="project_documents")
    op.drop_table("project_documents")
