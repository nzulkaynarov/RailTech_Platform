"""Отметка «Не работать» у клиента (Х-8): проекция компании ERP, четыре факта.

`clients.do_not_work_reason|by|at|until` — причина, кто и когда поставил, необязательный срок;
приходят в снимке `uz.railtech.erp.company.updated.v1` (поле `company.do_not_work`). Пусто —
отметки нет; «действует ли» считает код по сроку, флага нет. У прежних строк пусто — до первого
снимка клиент «рабочий». Данные не меняются.

Downgrade удаляет колонки.

Revision ID: cae4f42de3cd
Revises: 4d6593eef5f9
Create Date: 2026-11-23 12:12:07.473268+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cae4f42de3cd"
down_revision: str | Sequence[str] | None = "7b1e3c9a52d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("do_not_work_reason", sa.Text(), nullable=True))
    op.add_column("clients", sa.Column("do_not_work_by", sa.String(length=255), nullable=True))
    op.add_column("clients", sa.Column("do_not_work_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("do_not_work_until", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "do_not_work_until")
    op.drop_column("clients", "do_not_work_at")
    op.drop_column("clients", "do_not_work_by")
    op.drop_column("clients", "do_not_work_reason")
