"""Подписание документов уполномоченным лицом и проверка подлинности (SIGN-3, ADR-0024 п. 1–5)

`documents`:
- `signed_by_crm_user_id` — фактический подписант из реестра полномочий;
- `signed_at` — дата и время подписания документа;
- `signing_authority_id` — ссылка на запись реестра `signing_authorities`;
- `signatory_basis` — основание (`charter`, `order`, `power_of_attorney`);
- `signatory_basis_text` — формула основания («Действует по доверенности № … от …»);
- `acting_for_crm_user_id` — исходный держатель в случае замещения;
- `verification_code` — случайный код проверки (колонтитул, QR, /v/<код>);
- `dispatch_method` — способ отправки (`email`, `paper`, `courier`, `edo`, `other`).

Revision ID: c444cfe94f0d
Revises: b333bfe94f0c
Create Date: 2026-11-05 15:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c444cfe94f0d"
down_revision: str | Sequence[str] | None = "b333bfe94f0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("signed_by_crm_user_id", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "signing_authority_id",
            sa.Uuid(),
            sa.ForeignKey("signing_authorities.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("documents", sa.Column("signatory_basis", sa.String(length=24), nullable=True))
    op.add_column("documents", sa.Column("signatory_basis_text", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("acting_for_crm_user_id", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("verification_code", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("dispatch_method", sa.String(length=16), nullable=True))

    op.create_index(
        "uq_documents_verification_code",
        "documents",
        ["verification_code"],
        unique=True,
        postgresql_where=sa.text("verification_code IS NOT NULL"),
    )
    op.create_index("ix_documents_signed_by", "documents", ["signed_by_crm_user_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_signed_by", table_name="documents")
    op.drop_index("uq_documents_verification_code", table_name="documents")

    op.drop_column("documents", "dispatch_method")
    op.drop_column("documents", "verification_code")
    op.drop_column("documents", "acting_for_crm_user_id")
    op.drop_column("documents", "signatory_basis_text")
    op.drop_column("documents", "signatory_basis")
    op.drop_column("documents", "signing_authority_id")
    op.drop_column("documents", "signed_at")
    op.drop_column("documents", "signed_by_crm_user_id")
