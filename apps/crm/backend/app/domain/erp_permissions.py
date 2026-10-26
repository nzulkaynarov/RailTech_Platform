"""Карта «роль CRM → роль и права ERP» (FIX-11, S-11; docs/architecture/sso-token.md).

CRM — источник истины по людям (ADR-0003), ERP хранит только коды из своего каталога прав
(`accounts.constants.Permission`). Прежние коды карты (`quote.view`, `quote.edit`) в ERP не
существовали, а `quote.view_cost_margin` (себестоимость и маржа) получал каждый менеджер. Теперь:

- `admin` в CRM = суперпользователь ERP (все права, список ERP игнорирует);
- `manager` — рабочее место продаж: вести запросы и сделки, строить и отправлять КП с ценами.
  Себестоимости и маржи, финансов, договоров, настроек и команды нет;
- `viewer` — только просмотр (ни одного права).

Несколько ролей у одного человека — объединение, `admin` перекрывает остальные. Коды — только из
`ERP_PERMISSIONS`; сверка с каталогом ERP — в тестах (`tests/unit/domain/test_erp_permissions.py`:
снимок `ErpPermission` в `erp-integration.yaml` и сам каталог `accounts/constants.py`).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

ErpRole = Literal["admin", "backoffice"]

# Снимок каталога прав ERP (`accounts.constants.Permission`) — порядок как в каталоге.
ERP_PERMISSIONS: Final[tuple[str, ...]] = (
    "deal.manage",
    "deal.assign",
    "quote.build",
    "quote.edit_pricing",
    "quote.view_cost_margin",
    "quote.send",
    "quote.review",
    "contract.manage",
    "contract.sign",
    "catalog.manage",
    "catalog.publish",
    "supply.manage",
    "fulfillment.manage",
    "fulfillment.act",
    "finance.invoice",
    "finance.payment",
    "finance.rates",
    "settings.edit",
    "settings.charge_templates",
    "team.manage",
    "data.export",
)

MANAGER_PERMISSIONS: Final[tuple[str, ...]] = (
    "deal.manage",
    "quote.build",
    "quote.edit_pricing",
    "quote.send",
)

_BY_ROLE: Final[dict[str, tuple[str, ...]]] = {
    "admin": ERP_PERMISSIONS,
    "manager": MANAGER_PERMISSIONS,
    "viewer": (),
}


@dataclass(frozen=True, slots=True)
class ErpAccess:
    """Что получает пользователь в ERP: роль провижининга и коды прав (claim `permissions`)."""

    role: ErpRole
    permissions: tuple[str, ...]


def erp_access(roles: Iterable[str]) -> ErpAccess:
    """Роль и права ERP по ролям CRM; неизвестная роль не даёт ничего (код решает, не модель)."""
    held = {r for r in roles if r in _BY_ROLE}
    if "admin" in held:
        return ErpAccess("admin", ERP_PERMISSIONS)
    granted = {code for role in held for code in _BY_ROLE[role]}
    return ErpAccess("backoffice", tuple(c for c in ERP_PERMISSIONS if c in granted))
