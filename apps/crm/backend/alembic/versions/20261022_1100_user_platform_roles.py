"""users: platform_roles и position — роли и должность сотрудника Платформы (CRM-01)

`platform_roles` — JSON-массив кодов из `packages/contracts/platform-rbac.yaml` (MANAGER, DIRECTOR,
SUPPLY, ENGINEER, ACCOUNTANT, ADMIN), пусто по умолчанию (прежнее поведение: роли CRM и ERP
ведёт админ вручную). `position` — должность текстом, ≤ 120 символов (SPEC-v3 §4.3).

Revision ID: 0032_user_platform_roles
Revises: 0031_user_erp_role_codes
Create Date: 2026-10-22 11:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_user_platform_roles"
down_revision: str | None = "0031_user_erp_role_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "platform_roles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("position", sa.String(length=120), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_platform_roles"),
        "users",
        "jsonb_typeof(platform_roles) = 'array' "
        'AND platform_roles <@ CAST(\'["MANAGER", "DIRECTOR", "SUPPLY", "ENGINEER", '
        '"ACCOUNTANT", "ADMIN"]\' AS jsonb)',
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_platform_roles"), "users", type_="check")
    op.drop_column("users", "position")
    op.drop_column("users", "platform_roles")
