"""Оплата служебной записки: дата, сумма, платёжка бухгалтера (D2-4)

SPEC-v3 §3.2 п. 5, §2.4 «Служебная записка … Передана бухгалтеру → Оплачена»: оплата фиксируется операцией
`POST /documents/{id}/payment` (право `payments.confirm`), одна запись на документ.

Revision ID: 0007_document_payments
Revises: 0006_employee_sections
Create Date: 2026-10-28 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_document_payments"
down_revision: str | Sequence[str] | None = "0006_employee_sections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_payments",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("receipt_file_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("paid_by_crm_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_document_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_payments_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_file_id"],
            ["files.id"],
            name=op.f("fk_document_payments_receipt_file_id_files"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_document_payments")),
    )


def downgrade() -> None:
    op.drop_table("document_payments")
