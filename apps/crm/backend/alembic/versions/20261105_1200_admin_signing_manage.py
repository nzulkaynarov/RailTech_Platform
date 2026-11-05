"""Администратор: «Права подписи» — управление реестром полномочий (SIGN-2, ADR-0024 п. 1)

Что делает: у системной роли `ADMIN` раздел `eds.signing.manage` ставится в `full`:
управление реестром полномочий подписи (доверенности, приказы, уставы) и проверка полномочий;
каталог `platform-rbac.yaml` приведён в том же PR. Версия роли растёт. Роль, у которой раздел
уже настроен (администратор поправил сам), не меняется. Права EDS держателей роли
пересчитывает автопереопубликация по отпечатку каталога (`services/identity_catalog.py`).
Downgrade снимает раздел `eds.signing.manage` и тоже поднимает версию.

Revision ID: 44c4ccb1a36d
Revises: fefcc20f861d
Create Date: 2026-11-05 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "44c4ccb1a36d"
down_revision: str | None = "fefcc20f861d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADD_SIGNING_MANAGE = """
UPDATE platform_roles
SET access = access || '{"eds.signing.manage": "full"}'::jsonb,
    version = version + 1
WHERE code = 'ADMIN' AND access->>'eds.signing.manage' IS NULL
"""

_REMOVE_SIGNING_MANAGE = """
UPDATE platform_roles
SET access = access - 'eds.signing.manage',
    version = version + 1
WHERE code = 'ADMIN' AND access->>'eds.signing.manage' = 'full'
"""


def upgrade() -> None:
    op.execute(sa.text(_ADD_SIGNING_MANAGE))


def downgrade() -> None:
    op.execute(sa.text(_REMOVE_SIGNING_MANAGE))
