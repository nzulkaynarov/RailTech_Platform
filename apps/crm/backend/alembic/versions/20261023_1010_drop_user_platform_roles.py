"""users.platform_roles удалён: роли сотрудников живут в user_platform_roles (R-1, contract)

Третий шаг expand -> migrate -> contract: после переноса кодов в роли-данные (0035) столбец
`users.platform_roles` и его CHECK больше не нужны. Старое поле с кодами API отдаёт вычисленным
из ролей, у которых есть код (совместимость BFF до R-2).

Downgrade возвращает столбец и CHECK и заполняет его кодами из `user_platform_roles`
(`ADMIN`/`DIRECTOR` как есть, `tpl:<код>` -> `<код>`; роли без кода в старом формате не выразить).

Revision ID: 0036_drop_user_platform_roles
Revises: 0035_platform_roles_data
Create Date: 2026-10-23 10:10:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_drop_user_platform_roles"
down_revision: str | None = "0035_platform_roles_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL = """
UPDATE users u SET platform_roles = coalesce(
    (SELECT jsonb_agg(
         CASE WHEN r.code LIKE 'tpl:%' THEN substr(r.code, 5) ELSE r.code END
         ORDER BY array_position(
             ARRAY['MANAGER', 'DIRECTOR', 'SUPPLY', 'ENGINEER', 'ACCOUNTANT', 'ADMIN'],
             CASE WHEN r.code LIKE 'tpl:%' THEN substr(r.code, 5) ELSE r.code END))
     FROM user_platform_roles up JOIN platform_roles r ON r.id = up.role_id
     WHERE up.user_id = u.id
       AND r.code IN ('ADMIN', 'DIRECTOR', 'tpl:MANAGER', 'tpl:SUPPLY', 'tpl:ENGINEER',
                      'tpl:ACCOUNTANT')),
    '[]'::jsonb)
"""


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_platform_roles"), "users", type_="check")
    op.drop_column("users", "platform_roles")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "platform_roles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(_BACKFILL)
    op.create_check_constraint(
        op.f("ck_users_platform_roles"),
        "users",
        "jsonb_typeof(platform_roles) = 'array' "
        'AND platform_roles <@ CAST(\'["MANAGER", "DIRECTOR", "SUPPLY", "ENGINEER", '
        '"ACCOUNTANT", "ADMIN"]\' AS jsonb)',
    )
