"""Роли по навигации: менеджеру — расчёт, снабженцу — без клиентов CRM, директору — вся почта

0.3 плана 2026-11-12 (DECISIONS 2026-11-13; FR-7, FR-10, FR-13 прогона 2026-11-11):
- роли из шаблона «Менеджер» (`tpl:MANAGER`) получают `erp.calc: full` — менеджер ведёт заявку,
  расчёт и КП. Роль, где администратор уже задал `erp.calc` сам, не трогается;
- у ролей из шаблона «Снабженец» (`tpl:SUPPLY`) снимается `crm.clients: read` — в «Контрагентах»
  снабженец видит только партнёров каталога (`erp.stock`). Раздел `full` не трогается;
- системная роль `DIRECTOR` получает новый раздел `crm.mail: read` — вся очередь «Почты» без
  действий (`mail_inbox:read`).

Версия роли растёт. Признак базовой роли CRM не меняется (он зависит от `admin` и `crm.leads`).
Права ERP и EDS переопубликуются сами: шаблоны `tpl:*` входят в отпечаток каталога
(`services/identity_catalog.py`), политики casbin приложение сверяет с таблицей ролей при старте.

Downgrade возвращает `crm.clients: read` ролям `tpl:SUPPLY`, снимает `erp.calc: full` у ролей
`tpl:MANAGER` и `crm.mail` у роли `DIRECTOR`.

Revision ID: 867511904077
Revises: 44c4ccb1a36d
Create Date: 2026-11-13 03:34:32.864462+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "867511904077"
down_revision: str | Sequence[str] | None = "44c4ccb1a36d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MANAGER_CALC = """
UPDATE platform_roles
SET access = access || '{"erp.calc": "full"}'::jsonb,
    version = version + 1
WHERE code = 'tpl:MANAGER' AND NOT (access ? 'erp.calc')
"""
_SUPPLY_NO_CLIENTS = """
UPDATE platform_roles
SET access = access - 'crm.clients',
    version = version + 1
WHERE code = 'tpl:SUPPLY' AND access->>'crm.clients' = 'read'
"""
_DIRECTOR_MAIL = """
UPDATE platform_roles
SET access = access || '{"crm.mail": "read"}'::jsonb,
    version = version + 1
WHERE code = 'DIRECTOR' AND NOT (access ? 'crm.mail')
"""
_DIRECTOR_NO_MAIL = """
UPDATE platform_roles
SET access = access - 'crm.mail',
    version = version + 1
WHERE code = 'DIRECTOR' AND access ? 'crm.mail'
"""
_MANAGER_NO_CALC = """
UPDATE platform_roles
SET access = access - 'erp.calc',
    version = version + 1
WHERE code = 'tpl:MANAGER' AND access->>'erp.calc' = 'full'
"""
_SUPPLY_CLIENTS = """
UPDATE platform_roles
SET access = access || '{"crm.clients": "read"}'::jsonb,
    version = version + 1
WHERE code = 'tpl:SUPPLY' AND NOT (access ? 'crm.clients')
"""


def upgrade() -> None:
    op.execute(_MANAGER_CALC)
    op.execute(_SUPPLY_NO_CLIENTS)
    op.execute(_DIRECTOR_MAIL)


def downgrade() -> None:
    op.execute(_DIRECTOR_NO_MAIL)
    op.execute(_SUPPLY_CLIENTS)
    op.execute(_MANAGER_NO_CALC)
