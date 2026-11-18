"""Проекция реквизитов компании ERP у клиента (СУЩ-2.7, ADR-0028 п. 6): `clients.erp_requisites_at`.

Время последнего применённого снимка `uz.railtech.erp.company.updated.v1`: более старый снимок
название, ИНН, страну и рег. номер клиента не перезаписывает. У прежних строк пусто — первый
снимок применится. Данные не меняются.

Downgrade удаляет колонку.

Revision ID: 9b1daa0b361e
Revises: 8d58823f6312
Create Date: 2026-11-18 19:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b1daa0b361e"
down_revision: str | Sequence[str] | None = "8d58823f6312"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clients", sa.Column("erp_requisites_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("clients", "erp_requisites_at")
