"""users: language — язык интерфейса сотрудника ru|uz|en, по умолчанию ru (CRM-01b, Q-PLT-10-1 п. 6)

Revision ID: 0034_user_language
Revises: 0033_admin_platform_roles
Create Date: 2026-10-22 12:10:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_user_language"
down_revision: str | None = "0033_admin_platform_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language", sa.String(length=2), server_default=sa.text("'ru'"), nullable=False),
    )
    op.create_check_constraint(op.f("ck_users_language"), "users", "language IN ('ru', 'uz', 'en')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_language"), "users", type_="check")
    op.drop_column("users", "language")
