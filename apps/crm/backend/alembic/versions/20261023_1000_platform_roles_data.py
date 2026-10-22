"""platform_roles, user_platform_roles: роли Платформы как данные (R-1, ADR-0012), expand и migrate

Было: `users.platform_roles` — JSON-массив кодов (`MANAGER|DIRECTOR|SUPPLY|ENGINEER|
ACCOUNTANT|ADMIN`, миграции 0032–0034). Стало: таблица ролей `platform_roles` (матрица `access`:
раздел -> full|read, `restricted_fields`) и связь с сотрудниками `user_platform_roles`.

Что делает (expand + migrate; столбец `users.platform_roles` снимает следующая миграция 0036):
- создаёт обе таблицы (+ триггер `updated_at`);
- вставляет системные роли «Администратор» (`ADMIN`) и «Директор» (`DIRECTOR`) и роли из шаблонов
  «Менеджер», «Снабженец», «Гл. инженер», «Бухгалтер» (`tpl:MANAGER`, ...): снимок каталога
  `packages/contracts/platform-rbac.v2.yaml` на момент миграции, дальше они — обычные данные;
- переносит коды сотрудников в связи (`ADMIN`/`DIRECTOR` -> системные роли, остальные ->
  `tpl:<код>`);
  роли CRM, `platform_access` и `erp_role_codes` сотрудников не трогает;
- сотрудникам с ролями и доступом к ERP ставит в очередь `erp_provision_user`: права ERP
  пересчитываются по матрицам ролей (`permissions` вместо `role_codes`).
Политики casbin (`pr:<id>`) приложение сверяет с таблицей при старте.

Revision ID: 0035_platform_roles_data
Revises: 0034_user_language
Create Date: 2026-10-23 10:00:00+00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_platform_roles_data"
down_revision: str | None = "0034_user_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Снимок каталога v2 (системные роли и шаблоны); миграции замораживаются, каталог — нет.
ROLES = json.loads(
    r"""
[
    {
        "code": "ADMIN",
        "name": "Администратор",
        "is_system": true,
        "access": {
            "admin": "full",
            "company.settings": "full",
            "dashboard.queue": "full",
            "chats.internal": "full",
            "eds.memo.create": "full"
        },
        "restricted_fields": [],
        "description": "Сотрудники, роли, интеграции и тикеты. Бизнес-данные по умолчанию не видит."
    },
    {
        "code": "DIRECTOR",
        "name": "Директор",
        "is_system": true,
        "access": {
            "dashboard.queue": "full",
            "dashboard.summary": "full",
            "crm.leads": "full",
            "crm.clients": "full",
            "eds.inbox": "full",
            "eds.drafts": "full",
            "eds.projects": "full",
            "eds.payments": "full",
            "eds.memo.create": "full",
            "eds.memo.approve": "full",
            "erp.calc": "full",
            "erp.calc.goods": "full",
            "erp.calc.services": "full",
            "erp.stock": "full",
            "chats.internal": "full",
            "chats.external": "full",
            "company.settings": "full",
            "admin": "read"
        },
        "restricted_fields": [
            "cost_margin",
            "supplier_prices"
        ],
        "description": "Все бизнес-разделы с полным доступом и утверждения; Admin — чтение."
    },
    {
        "code": "tpl:MANAGER",
        "name": "Менеджер",
        "is_system": false,
        "access": {
            "dashboard.queue": "full",
            "crm.leads": "full",
            "crm.clients": "full",
            "eds.inbox": "read",
            "eds.drafts": "read",
            "eds.projects": "read",
            "eds.payments": "read",
            "eds.memo.create": "full",
            "erp.stock": "read",
            "chats.internal": "full",
            "chats.external": "full"
        },
        "restricted_fields": [],
        "description": "Создана из шаблона «Менеджер»."
    },
    {
        "code": "tpl:SUPPLY",
        "name": "Снабженец",
        "is_system": false,
        "access": {
            "dashboard.queue": "full",
            "crm.clients": "read",
            "eds.projects": "read",
            "eds.memo.create": "full",
            "erp.calc": "full",
            "erp.calc.goods": "full",
            "erp.stock": "full",
            "chats.internal": "full"
        },
        "restricted_fields": [
            "cost_margin",
            "supplier_prices"
        ],
        "description": "Создана из шаблона «Снабженец»."
    },
    {
        "code": "tpl:ENGINEER",
        "name": "Гл. инженер",
        "is_system": false,
        "access": {
            "dashboard.queue": "full",
            "crm.clients": "read",
            "eds.projects": "read",
            "eds.memo.create": "full",
            "erp.calc": "full",
            "erp.calc.services": "full",
            "erp.stock": "full",
            "chats.internal": "full"
        },
        "restricted_fields": [],
        "description": "Создана из шаблона «Гл. инженер»."
    },
    {
        "code": "tpl:ACCOUNTANT",
        "name": "Бухгалтер",
        "is_system": false,
        "access": {
            "dashboard.queue": "full",
            "dashboard.summary": "read",
            "crm.clients": "read",
            "eds.inbox": "read",
            "eds.projects": "full",
            "eds.payments": "full",
            "eds.memo.create": "full",
            "erp.calc": "read",
            "erp.stock": "read",
            "chats.internal": "full",
            "chats.external": "full"
        },
        "restricted_fields": [
            "totals_only",
            "supplier_prices"
        ],
        "description": "Создана из шаблона «Бухгалтер»."
    }
]
"""
)

_MOVE_CODES = """
INSERT INTO user_platform_roles (user_id, role_id)
SELECT u.id, r.id
FROM users u
CROSS JOIN LATERAL jsonb_array_elements_text(u.platform_roles) AS c(code)
JOIN platform_roles r
  ON r.code = CASE WHEN c.code IN ('ADMIN', 'DIRECTOR') THEN c.code ELSE 'tpl:' || c.code END
ON CONFLICT DO NOTHING
"""
_RECOMPUTE_TARGETS = """
SELECT id FROM users
WHERE is_active AND platform_roles <> '[]'::jsonb AND platform_access ? 'erp'
ORDER BY id
"""


def upgrade() -> None:
    op.create_table(
        "platform_roles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "access",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "restricted_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(access) = 'object'", name=op.f("ck_platform_roles_access")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(restricted_fields) = 'array'",
            name=op.f("ck_platform_roles_restricted_fields"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_platform_roles_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_platform_roles_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_platform_roles_code")),
    )
    op.execute("CREATE UNIQUE INDEX uq_platform_roles_lower_name ON platform_roles (lower(name))")
    op.execute(
        "CREATE TRIGGER trg_platform_roles_updated_at BEFORE UPDATE ON platform_roles "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.create_table(
        "user_platform_roles",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("granted_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_platform_roles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["platform_roles.id"],
            name=op.f("fk_user_platform_roles_role_id_platform_roles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_user_platform_roles_granted_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_platform_roles")),
    )
    op.create_index("ix_user_platform_roles_role_id", "user_platform_roles", ["role_id"])
    _seed_roles()
    conn = op.get_bind()
    conn.execute(sa.text(_MOVE_CODES))
    for (user_id,) in conn.execute(sa.text(_RECOMPUTE_TARGETS)).all():
        conn.execute(
            sa.text(
                "SELECT procrastinate_defer_jobs_v1(ARRAY[ROW('notify', 'erp_provision_user', "
                "0, :lock, NULL, CAST(:args AS jsonb), NULL)::procrastinate_job_to_defer_v1])"
            ),
            {"lock": f"erp_user:{user_id}", "args": f'{{"user_id": {user_id}}}'},
        )


def _seed_roles() -> None:
    conn = op.get_bind()
    insert = sa.text(
        "INSERT INTO platform_roles "
        "(code, name, description, is_system, access, restricted_fields) "
        "VALUES (:code, :name, :description, :is_system, CAST(:access AS jsonb), "
        "CAST(:fields AS jsonb))"
    )
    for role in ROLES:
        conn.execute(
            insert,
            {
                "code": role["code"],
                "name": role["name"],
                "description": role["description"],
                "is_system": role["is_system"],
                "access": json.dumps(role["access"]),
                "fields": json.dumps(role["restricted_fields"]),
            },
        )


def downgrade() -> None:
    op.drop_table("user_platform_roles")
    op.drop_table("platform_roles")
