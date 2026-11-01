"""Карточка входящего для делопроизводства (P8, SPEC-v3 §3.2a п. 1; бенчмарк СЭД 2026-11-01 §6.3)

Новые поля письма: вид документа (код справочника `services/letter_kinds.py`), способ получения, подписал, срок по
документу, связь с предыдущим ВХ или нашим ИСХ; индекс исходящего номера отправителя для проверки дубля. Все поля
необязательные: письма по заявкам ERP их не заполняют. Downgrade удаляет поля и индекс.

Revision ID: 7d0f20a58e24
Revises: 0008_project_documents
Create Date: 2026-11-01 15:20:55.280711+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d0f20a58e24"
down_revision: str | Sequence[str] | None = "0008_project_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("letters", sa.Column("doc_kind", sa.String(length=32), nullable=True))
    op.add_column("letters", sa.Column("receipt_method", sa.String(length=24), nullable=True))
    op.add_column("letters", sa.Column("signed_by", sa.String(length=255), nullable=True))
    op.add_column("letters", sa.Column("document_due", sa.Date(), nullable=True))
    op.add_column("letters", sa.Column("related_letter_id", sa.Uuid(), nullable=True))
    op.add_column("letters", sa.Column("related_document_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_letters_related_letter_id_letters"),
        "letters",
        "letters",
        ["related_letter_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_letters_related_document_id_documents"),
        "letters",
        "documents",
        ["related_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_letters_receipt_method"),
        "letters",
        "receipt_method IS NULL OR receipt_method IN ('post', 'paper', 'taxpayer_cabinet', 'courier', 'email')",
    )
    op.create_index(
        "ix_letters_sender_ref_number",
        "letters",
        ["sender_ref_number"],
        postgresql_where=sa.text("sender_ref_number IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_letters_sender_ref_number", table_name="letters")
    op.drop_constraint(op.f("ck_letters_receipt_method"), "letters", type_="check")
    op.drop_constraint(op.f("fk_letters_related_document_id_documents"), "letters", type_="foreignkey")
    op.drop_constraint(op.f("fk_letters_related_letter_id_letters"), "letters", type_="foreignkey")
    for column in (
        "related_document_id",
        "related_letter_id",
        "document_due",
        "signed_by",
        "receipt_method",
        "doc_kind",
    ):
        op.drop_column("letters", column)
