"""Роли Платформы и их карта в CRM и ERP. ГЕНЕРИРУЕТСЯ — не править руками (CRM-01).

Источник: packages/contracts/platform-rbac.yaml (version 1). Пересоздание:
`make -C apps/crm platform-roles`; тест `tests/unit/domain/test_platform_roles.py` сверяет
файл с контрактом.
"""

from typing import Final, Literal

PlatformRoleCode = Literal["MANAGER", "DIRECTOR", "SUPPLY", "ENGINEER", "ACCOUNTANT", "ADMIN"]

PLATFORM_ROLE_CODES: Final[tuple[str, ...]] = (
    "MANAGER",
    "DIRECTOR",
    "SUPPLY",
    "ENGINEER",
    "ACCOUNTANT",
    "ADMIN",
)

# Базовая роль CRM (admin > manager > viewer при нескольких ролях).
CRM_BASE_ROLE: Final[dict[str, str]] = {
    "MANAGER": "manager",
    "DIRECTOR": "viewer",
    "SUPPLY": "viewer",
    "ENGINEER": "viewer",
    "ACCOUNTANT": "manager",
    "ADMIN": "admin",
}

# Системные роли ERP -> `role_codes` провижининга.
ERP_ROLE_CODES: Final[dict[str, tuple[str, ...]]] = {
    "MANAGER": ("VIEWER",),
    "DIRECTOR": ("HEAD",),
    "SUPPLY": ("CATALOG_SUPPLY", "FULFILLMENT"),
    "ENGINEER": ("FULFILLMENT",),
    "ACCOUNTANT": ("FINANCE",),
    "ADMIN": (),
}

# Права ERP поверх шаблонов ролей -> `permissions` провижининга.
ERP_EXTRA_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    "MANAGER": ("deal.manage",),
    "DIRECTOR": (),
    "SUPPLY": ("quote.build", "quote.edit_pricing"),
    "ENGINEER": ("quote.build",),
    "ACCOUNTANT": ("contract.manage", "fulfillment.act"),
    "ADMIN": (),
}
