"""Адресат исходящего письма — ссылка на компанию ERP и человека (СУЩ-2.6, ADR-0028 п. 5).

`documents.recipient_company_id` (с индексом — письма компании в её карточке) и `recipient_contact_id`; название и ИНН
остаются снимком карточки ERP. У писем до этой миграции колонки пусты: адресат текстом, экран просит сопоставить. На
проде на 2026-11-18 — 5 исходящих, ни у одного нет ИНН: автоматически не связывается ни одно. Откат удаляет колонки.

Revision ID: 0df7595a52d6
Revises: 2da01a5477bc
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0df7595a52d6"
down_revision: str | Sequence[str] | None = "2da01a5477bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("recipient_company_id", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("recipient_contact_id", sa.BigInteger(), nullable=True))
    op.create_index(op.f("ix_documents_recipient_company_id"), "documents", ["recipient_company_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_recipient_company_id"), table_name="documents")
    op.drop_column("documents", "recipient_contact_id")
    op.drop_column("documents", "recipient_company_id")
