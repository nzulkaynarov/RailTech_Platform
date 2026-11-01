"""Роли пилота и регистрация входящих отдельно от резолюции (P8; W-2; аудит UI R1, R2)

Что делает:
- вставляет роли из шаблонов пилота «Делопроизводитель» (`tpl:REGISTRAR`) и
  «Менеджер-универсал» (`tpl:MANAGER_ALL`) — снимок каталога `platform-rbac.yaml` на момент
  миграции, дальше это обычные редактируемые роли (ADR-0012 п. 3). Роль с тем же кодом или
  именем уже есть (администратор завёл сам) — вставка пропускается, роль не меняется;
- каждой роли с `eds.inbox: full` (системный «Директор», роли администратора) даёт новый
  раздел `eds.inbox.register: full`: код EDS `letters.register` переехал из `eds.inbox` в
  `eds.inbox.register`, права EDS держателей резолюции не меняются. Версия роли растёт.

Политики casbin (`pr:<id>`) приложение сверяет с таблицей при старте; права EDS сотрудников
переопубликует воркер по отпечатку каталога (`services/identity_catalog.py`, шаблоны `tpl:*`
входят в отпечаток); ERP не меняется (раздел прав ERP не даёт). Ручных шагов на проде нет.

Downgrade удаляет обе роли, если они никому не выданы (выданную роль не трогает: связь RESTRICT), и
снимает `eds.inbox.register` с ролей, у которых есть `eds.inbox: full`, с ростом версии.

Revision ID: bf63b9342895
Revises: ac71231f330f
Create Date: 2026-11-01 15:19:00.485263+00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bf63b9342895"
down_revision: str | Sequence[str] | None = "ac71231f330f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Снимок каталога (шаблоны пилота); миграции замораживаются, каталог — нет.
ROLES = json.loads(
    r"""
[
    {
        "code": "tpl:REGISTRAR",
        "name": "Делопроизводитель",
        "access": {
            "dashboard.queue": "full",
            "crm.leads": "full",
            "crm.clients": "read",
            "eds.inbox": "read",
            "eds.inbox.register": "full",
            "eds.projects": "read",
            "eds.memo.create": "full",
            "chats.internal": "full",
            "chats.external": "read"
        },
        "restricted_fields": [],
        "description": "Создана из шаблона «Делопроизводитель»."
    },
    {
        "code": "tpl:MANAGER_ALL",
        "name": "Менеджер-универсал",
        "access": {
            "dashboard.queue": "full",
            "crm.leads": "full",
            "crm.clients": "full",
            "eds.inbox": "read",
            "eds.drafts": "read",
            "eds.projects": "full",
            "eds.payments": "full",
            "eds.memo.create": "full",
            "erp.calc": "full",
            "erp.calc.goods": "full",
            "erp.calc.services": "full",
            "erp.stock": "full",
            "chats.internal": "full",
            "chats.external": "full"
        },
        "restricted_fields": ["cost_margin", "supplier_prices"],
        "description": "Создана из шаблона «Менеджер-универсал»."
    }
]
"""
)

_INSERT = sa.text(
    "INSERT INTO platform_roles (code, name, description, is_system, access, restricted_fields) "
    "VALUES (:code, :name, :description, false, CAST(:access AS jsonb), CAST(:fields AS jsonb)) "
    "ON CONFLICT DO NOTHING"
)
_GRANT_REGISTER = """
UPDATE platform_roles
SET access = access || '{"eds.inbox.register": "full"}'::jsonb,
    version = version + 1
WHERE access->>'eds.inbox' = 'full' AND NOT access ? 'eds.inbox.register'
"""
_REVOKE_REGISTER = """
UPDATE platform_roles
SET access = access - 'eds.inbox.register',
    version = version + 1
WHERE access->>'eds.inbox' = 'full' AND access ? 'eds.inbox.register'
"""
_DELETE_UNUSED = sa.text(
    "DELETE FROM platform_roles r WHERE r.code = :code "
    "AND NOT EXISTS (SELECT 1 FROM user_platform_roles u WHERE u.role_id = r.id)"
)


def upgrade() -> None:
    op.execute(sa.text(_GRANT_REGISTER))
    bind = op.get_bind()
    for role in ROLES:
        bind.execute(
            _INSERT,
            {
                "code": role["code"],
                "name": role["name"],
                "description": role["description"],
                "access": json.dumps(role["access"], ensure_ascii=False),
                "fields": json.dumps(role["restricted_fields"]),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for role in reversed(ROLES):
        bind.execute(_DELETE_UNUSED, {"code": role["code"]})
    op.execute(sa.text(_REVOKE_REGISTER))
