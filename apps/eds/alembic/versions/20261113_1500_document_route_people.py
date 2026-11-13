"""Согласующие от автора и получатели копии документа (пункт 1.6 плана): два списка `crm_user_id` в `documents`.
Пустые по умолчанию — прежние документы идут по шаблону, как раньше. Откат удаляет колонки.

Revision ID: 1ab826e3a38f
Revises: 87c14728e40c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1ab826e3a38f"
down_revision: str | Sequence[str] | None = "87c14728e40c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("extra_approvers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "documents",
        sa.Column("watchers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("documents", "watchers")
    op.drop_column("documents", "extra_approvers")
