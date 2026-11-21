"""СЦ-9 P11: `journal.on_behalf_of_crm_user_id` — действие заместителя «за» замещаемого.

Пусто у всех прежних строк и у действий «за себя». Откат удаляет колонку.

Revision ID: 5b7e2d9a4c61
Revises: 99d980a0287c
Create Date: 2026-11-21 14:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b7e2d9a4c61"
down_revision: str | Sequence[str] | None = "99d980a0287c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("journal", sa.Column("on_behalf_of_crm_user_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("journal", "on_behalf_of_crm_user_id")
