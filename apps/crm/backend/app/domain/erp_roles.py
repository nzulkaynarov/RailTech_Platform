"""Системные роли бэк-офиса ERP, которые админ CRM выдаёт сотруднику (FIX-63, Q-FIX50-1 (1)).

Перечень — снимок `SystemRoleCode` из `packages/contracts/openapi/erp-integration.yaml` (он же
`accounts.constants.BackofficeRoleCode` ERP). Выбор админа хранится в `users.erp_role_codes` и
уходит в провижининг как `role_codes`; права ролей ведёт ERP (шаблоны `ROLE_TEMPLATES`), CRM
знает только коды. Названия для интерфейса (ru/uz/en) — во фронтенде
(`frontend/src/domain/erpRoles.ts`). Сверка с контрактом и каталогом ERP — в тестах
(`tests/unit/domain/test_erp_roles.py`).
"""

from collections.abc import Iterable
from typing import Final, Literal

ErpRoleCode = Literal["CALCULATION", "CATALOG_SUPPLY", "FULFILLMENT", "FINANCE", "HEAD", "VIEWER"]

# Порядок каталога ERP (BUSINESS §11): Расчёт → Каталог и закупки → Исполнение → Финансы →
# Руководитель → Наблюдатель.
ERP_ROLE_CODES: Final[tuple[str, ...]] = (
    "CALCULATION",
    "CATALOG_SUPPLY",
    "FULFILLMENT",
    "FINANCE",
    "HEAD",
    "VIEWER",
)


def normalize_erp_roles(codes: Iterable[str]) -> list[str]:
    """Коды без дублей в порядке каталога; чужой код — `ValueError` (код решает, не модель)."""
    held = set(codes)
    unknown = held - set(ERP_ROLE_CODES)
    if unknown:
        raise ValueError(f"unknown erp role codes: {sorted(unknown)}")
    return [code for code in ERP_ROLE_CODES if code in held]
