"""users: erp_role_codes — системные роли ERP, выданные из CRM (FIX-63, Q-FIX50-1 (1))

Админ CRM выбирает сотруднику с доступом к ERP системные роли бэк-офиса («Расчёт», «Финансы»,
«Руководитель» …); выбор уходит в провижининг как `role_codes`. JSON-массив кодов каталога
(`domain/erp_roles.py`), пусто по умолчанию.

Revision ID: 0031_user_erp_role_codes
Revises: 0030_lead_consent_erp_request
Create Date: 2026-10-21 13:47:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_user_erp_role_codes"
down_revision: str | None = "0030_lead_consent_erp_request"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "erp_role_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_users_erp_role_codes"),
        "users",
        "jsonb_typeof(erp_role_codes) = 'array' "
        'AND erp_role_codes <@ CAST(\'["CALCULATION", "CATALOG_SUPPLY", "FULFILLMENT", '
        '"FINANCE", "HEAD", "VIEWER"]\' AS jsonb)',
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_erp_role_codes"), "users", type_="check")
    op.drop_column("users", "erp_role_codes")
