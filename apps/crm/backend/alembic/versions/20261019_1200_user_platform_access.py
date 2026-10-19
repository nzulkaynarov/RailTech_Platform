"""users: platform_access (доступ к ERP) и erp_sync_error (FIX-11, M3-CRM-06)

Revision ID: 0026_user_platform_access
Revises: 0025_sso_replay_tokens
Create Date: 2026-10-19 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_user_platform_access"
down_revision: str | None = "0025_sso_replay_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "platform_access",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("""'["crm"]'::jsonb"""),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_users_platform_access"),
        "users",
        "jsonb_typeof(platform_access) = 'array' "
        "AND platform_access @> CAST('[\"crm\"]' AS jsonb) "
        'AND platform_access <@ CAST(\'["crm", "erp"]\' AS jsonb)',
    )
    op.add_column("users", sa.Column("erp_sync_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "erp_sync_error")
    op.drop_constraint(op.f("ck_users_platform_access"), "users", type_="check")
    op.drop_column("users", "platform_access")
