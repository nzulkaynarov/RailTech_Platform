"""«Передать в работу» (план 1.9): объект, в который передано письмо, — `instructions.handed_to` (JSONB {kind, ref, number}).
Пусто у прежних поручений. Откат удаляет колонку.

Revision ID: 2da01a5477bc
Revises: 1ab826e3a38f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2da01a5477bc"
down_revision: str | Sequence[str] | None = "1ab826e3a38f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("instructions", sa.Column("handed_to", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("instructions", "handed_to")
