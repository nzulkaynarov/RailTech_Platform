"""Визы договора, счёта и акта: раздел визы бухгалтера и роль «Юрист» (ADR-0025, план 0.8)

Что делает:
- каждой роли с `eds.payments: full` (шаблон «Бухгалтер», «Менеджер-универсал», роли
  администратора, которые подтверждают оплату) даёт новый раздел `eds.visa.finance: full` — право
  EDS `approvals.visa_finance`: виза бухгалтера в маршруте подписи договора, счёта и акта. Версия
  роли растёт; роль, где раздел уже настроен, не меняется;
- вставляет роль из шаблона «Юрист» (`tpl:LAWYER`, правило владельца 13) — снимок каталога
  `platform-rbac.yaml` на момент миграции; дальше это обычная редактируемая роль (ADR-0012 п. 3).
  Роль с тем же кодом или именем уже есть — вставка пропускается.

Права EDS сотрудников переопубликует воркер по отпечатку каталога
(`services/identity_catalog.py`). Роль «Юрист» никому не выдаётся: администратор назначает её сам,
без неё договор не уйдёт на подпись (EDS ответит причиной).

Downgrade удаляет роль «Юрист», если она никому не выдана, и снимает `eds.visa.finance` с ролей, у
которых есть `eds.payments: full`, с ростом версии.

Revision ID: 09cbac1c437d
Revises: 867511904077
Create Date: 2026-11-14 15:00:00+00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "09cbac1c437d"
down_revision: str | Sequence[str] | None = "867511904077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LAWYER = {
    "code": "tpl:LAWYER",
    "name": "Юрист",
    "access": {
        "dashboard.queue": "full",
        "crm.clients": "read",
        "eds.inbox": "read",
        "eds.projects": "read",
        "eds.visa.legal": "full",
        "eds.memo.create": "full",
        "chats.internal": "full",
    },
    "restricted_fields": ["totals_only"],
    "description": "Создана из шаблона «Юрист».",
}

_INSERT = sa.text(
    "INSERT INTO platform_roles (code, name, description, is_system, access, restricted_fields) "
    "SELECT CAST(:code AS varchar), CAST(:name AS varchar), CAST(:description AS text), false, "
    "CAST(:access AS jsonb), CAST(:fields AS jsonb) "
    "WHERE NOT EXISTS (SELECT 1 FROM platform_roles "
    "WHERE code = CAST(:code AS varchar) OR name = CAST(:name AS varchar))"
)
_GRANT_VISA = """
UPDATE platform_roles
SET access = access || '{"eds.visa.finance": "full"}'::jsonb,
    version = version + 1
WHERE access->>'eds.payments' = 'full' AND NOT access ? 'eds.visa.finance'
"""
_REVOKE_VISA = """
UPDATE platform_roles
SET access = access - 'eds.visa.finance',
    version = version + 1
WHERE access->>'eds.payments' = 'full' AND access ? 'eds.visa.finance'
"""
_DELETE_UNUSED = sa.text(
    "DELETE FROM platform_roles r WHERE r.code = :code "
    "AND NOT EXISTS (SELECT 1 FROM user_platform_roles u WHERE u.role_id = r.id)"
)


def upgrade() -> None:
    op.execute(sa.text(_GRANT_VISA))
    op.get_bind().execute(
        _INSERT,
        {
            "code": LAWYER["code"],
            "name": LAWYER["name"],
            "description": LAWYER["description"],
            "access": json.dumps(LAWYER["access"], ensure_ascii=False),
            "fields": json.dumps(LAWYER["restricted_fields"]),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(_DELETE_UNUSED, {"code": LAWYER["code"]})
    op.execute(sa.text(_REVOKE_VISA))
