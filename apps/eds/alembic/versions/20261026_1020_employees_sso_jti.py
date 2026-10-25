"""employees и sso_jti: проекция сотрудников и одноразовые jti обмена SSO-токена

Волна 12, E2 (решение лида L-C1-1, docs/architecture/sso-token.md «Токен сотрудника для EDS»):
* `employees` — проекция сотрудников из `identity.user.*` с правами `permissions.eds`; пишет только обработчик шины;
* `sso_jti` — использованные `jti` SSO-токенов CRM (10 минут, уборка — задачей `sso_jti_cleanup`).

Revision ID: 0003_employees_sso_jti
Revises: 0002_rt_bus
Create Date: 2026-10-26 10:20:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_employees_sso_jti"
down_revision: str | Sequence[str] | None = "0002_rt_bus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("crm_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.String(length=120), nullable=True),
        sa.Column("language", sa.String(length=2), server_default="ru", nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "permissions_eds",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_id", sa.Uuid(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("language IN ('ru', 'uz', 'en')", name=op.f("ck_employees_language")),
        sa.PrimaryKeyConstraint("crm_user_id", name=op.f("pk_employees")),
    )
    op.create_table(
        "sso_jti",
        sa.Column("jti", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("jti", name=op.f("pk_sso_jti")),
    )
    op.create_index(op.f("ix_sso_jti_expires_at"), "sso_jti", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sso_jti_expires_at"), table_name="sso_jti")
    op.drop_table("sso_jti")
    op.drop_table("employees")
