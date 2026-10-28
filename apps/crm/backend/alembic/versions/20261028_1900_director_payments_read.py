"""Директор: «Счета и оплаты» — только чтение (D2-4, решение архитектора по Q-D2-4-1 п. 1)

Что делает: у системной роли `DIRECTOR` раздел `eds.payments` ставится в `read` (был `full`):
оплату подтверждает бухгалтер, директор читает счета и платит служебки только через роль
бухгалтера; каталог `platform-rbac.yaml` приведён в том же PR. Версия роли растёт. Роль, у которой
раздел уже не `full` (администратор поправил сам), не меняется. Права EDS и ERP держателей роли
пересчитывает автопереопубликация по отпечатку каталога (`services/identity_catalog.py`).
Downgrade возвращает `full` и тоже поднимает версию.

Revision ID: 0049_director_payments_read
Revises: aa1221ec032b
Create Date: 2026-10-28 19:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_director_payments_read"
down_revision: str | None = "aa1221ec032b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_READ = """
UPDATE platform_roles
SET access = access || '{"eds.payments": "read"}'::jsonb,
    version = version + 1
WHERE code = 'DIRECTOR' AND access->>'eds.payments' = 'full'
"""
_FULL = """
UPDATE platform_roles
SET access = access || '{"eds.payments": "full"}'::jsonb,
    version = version + 1
WHERE code = 'DIRECTOR' AND access->>'eds.payments' = 'read'
"""


def upgrade() -> None:
    op.execute(sa.text(_READ))


def downgrade() -> None:
    op.execute(sa.text(_FULL))
