"""Роль-шаблон «Бухгалтер» без цен поставщиков (D2-1, решение архитектора по Q-D2-1-4)

Что делает: у роли `tpl:ACCOUNTANT` из `restricted_fields` убирается `supplier_prices` (бухгалтер
видит цены клиенту, итоги и НДС — без цен поставщиков, себестоимости и маржи; каталог
`platform-rbac.yaml` приведён в том же PR), версия роли растёт. Права ERP от `supplier_prices` не
зависят (`backend.erp: []`), провижининг не нужен. Роль, у которой поля уже нет (администратор
поправил сам), не меняется. Downgrade возвращает поле и тоже поднимает версию.

Revision ID: 0044_accountant_supplier_prices
Revises: 0043_messages_bot_created_idx
Create Date: 2026-10-28 17:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_accountant_supplier_prices"
down_revision: str | None = "0043_messages_bot_created_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP = """
UPDATE platform_roles
SET restricted_fields = restricted_fields - 'supplier_prices',
    version = version + 1
WHERE code = 'tpl:ACCOUNTANT' AND restricted_fields ? 'supplier_prices'
"""
_RESTORE = """
UPDATE platform_roles
SET restricted_fields = restricted_fields || '["supplier_prices"]'::jsonb,
    version = version + 1
WHERE code = 'tpl:ACCOUNTANT' AND NOT restricted_fields ? 'supplier_prices'
"""


def upgrade() -> None:
    op.execute(sa.text(_DROP))


def downgrade() -> None:
    op.execute(sa.text(_RESTORE))
