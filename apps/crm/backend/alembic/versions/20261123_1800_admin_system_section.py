"""Администратор: раздел `admin.system` — страницы фундамента Настроек (ЕВ-2а)

Что делает: у системной роли `ADMIN` раздел `admin.system` ставится в `full` — каналы и
подключения, ИИ, выгрузки открывает только администратор; каталог `platform-rbac.yaml` приведён
в том же PR. Версия роли растёт. Роль, у которой раздел уже настроен, не меняется. Права
бэкендов раздел не даёт (`admin` остаётся прежним).
Downgrade снимает раздел и тоже поднимает версию.

Revision ID: 5a8e2c1f7b30
Revises: cae4f42de3cd
Create Date: 2026-11-23 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5a8e2c1f7b30"
down_revision: str | None = "cae4f42de3cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADD = """
UPDATE platform_roles
SET access = access || '{"admin.system": "full"}'::jsonb,
    version = version + 1
WHERE code = 'ADMIN' AND access->>'admin.system' IS NULL
"""

_REMOVE = """
UPDATE platform_roles
SET access = access - 'admin.system',
    version = version + 1
WHERE code = 'ADMIN' AND access->>'admin.system' = 'full'
"""


def upgrade() -> None:
    op.execute(sa.text(_ADD))


def downgrade() -> None:
    op.execute(sa.text(_REMOVE))
