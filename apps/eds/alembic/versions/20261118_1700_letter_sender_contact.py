"""Отправитель входящего письма — ссылка на человека компании ERP (СУЩ-2.6, ADR-0028 п. 5).

`letters.sender_contact_id`; компания-отправитель — прежняя связь `letters.erp_company_id`. Название, ИНН и контакт
остаются снимком. У писем до этой миграции колонка пуста. На проде на 2026-11-18 — 18 входящих, ИНН отправителя нет ни
у одного: автоматически не связывается ни одно. Откат удаляет колонку.

Revision ID: 7c41e2b9d5f3
Revises: 0df7595a52d6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c41e2b9d5f3"
down_revision: str | Sequence[str] | None = "0df7595a52d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("letters", sa.Column("sender_contact_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("letters", "sender_contact_id")
