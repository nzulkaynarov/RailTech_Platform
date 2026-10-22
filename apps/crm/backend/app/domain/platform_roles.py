"""Роли Платформы -> доступ в CRM и ERP (CRM-01, ADR-0011, SPEC-v3 §4).

Карта ролей — сгенерированный из `packages/contracts/platform-rbac.yaml` модуль
`platform_roles_generated.py`; здесь только правила поверх неё (чистые функции, без I/O):

- непустой `users.platform_roles` вычисляет базовую роль CRM (старшая из ролей: admin > manager >
  viewer), `platform_access = ["crm", "erp"]`, `erp_role_codes` (объединение) и права ERP поверх
  шаблонов ролей (объединение `erp_extra_permissions`);
- пустой список — прежнее поведение: роли CRM, `platform_access` и `erp_role_codes` ведёт админ
  вручную;
- точечные права CRM поверх базовой роли (`PLATFORM_ROLE_GRANTS`, CRM-01c): директор (базовая роль
  `viewer`) читает сотрудников для «Admin · Оргструктура» Платформы.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from app.domain.erp_permissions import ERP_PERMISSIONS, ErpAccess
from app.domain.erp_roles import ERP_ROLE_CODES as ERP_CATALOG_ROLE_CODES
from app.domain.platform_roles_generated import (
    CRM_BASE_ROLE,
    ERP_EXTRA_PERMISSIONS,
    ERP_ROLE_CODES,
    PLATFORM_ROLE_CODES,
    PlatformRoleCode,
)

__all__ = [
    "PLATFORM_ROLE_GRANTS",
    "DerivedAccess",
    "PlatformRoleCode",
    "derive_access",
    "erp_access_for",
    "normalize_platform_roles",
    "normalize_position",
    "platform_grants",
]

POSITION_MAX_LEN: Final = 120
# Старшинство базовых ролей CRM при нескольких ролях Платформы.
_CRM_RANK: Final[tuple[str, ...]] = ("admin", "manager", "viewer")


# Права casbin `(ресурс, действие)`, которые роль Платформы даёт сверх базовой роли CRM (CRM-01c,
# Q-PLT-15-1 п. 1). Источник — раздел `admin` матрицы `platform-rbac.yaml`: DIRECTOR = read (только
# чтение сотрудников), ADMIN = full (и так `admin` CRM), остальные роли — hidden. Seed `viewer` не
# расширяется: иначе SUPPLY и ENGINEER (тоже `viewer`) читали бы всех сотрудников.
PLATFORM_ROLE_GRANTS: Final[dict[str, frozenset[tuple[str, str]]]] = {
    "DIRECTOR": frozenset({("users", "read")}),
}


@dataclass(frozen=True, slots=True)
class DerivedAccess:
    """Что вычисляется из набора ролей Платформы."""

    crm_role: str
    platform_access: tuple[str, ...]
    erp_role_codes: tuple[str, ...]
    erp_extra_permissions: tuple[str, ...]


def normalize_platform_roles(codes: Iterable[str]) -> list[str]:
    """Коды без дублей в порядке контракта; чужой код — `ValueError` (код решает, не модель)."""
    held = set(codes)
    unknown = held - set(PLATFORM_ROLE_CODES)
    if unknown:
        raise ValueError(f"unknown platform role codes: {sorted(unknown)}")
    return [code for code in PLATFORM_ROLE_CODES if code in held]


def normalize_position(value: str | None) -> str | None:
    """Должность (SPEC-v3 §4.3): обрезанный текст ≤ 120 символов; пусто — `None`."""
    text = (value or "").strip()
    if len(text) > POSITION_MAX_LEN:
        raise ValueError(f"position is longer than {POSITION_MAX_LEN} characters")
    return text or None


def platform_grants(codes: Iterable[str]) -> frozenset[tuple[str, str]]:
    """Права `(ресурс, действие)` поверх базовой роли CRM по ролям Платформы; чужие коды — пусто."""
    return frozenset(g for code in codes for g in PLATFORM_ROLE_GRANTS.get(code, frozenset()))


def derive_access(codes: Iterable[str]) -> DerivedAccess:
    """Доступ по непустому набору ролей Платформы: объединение карты контракта."""
    roles = normalize_platform_roles(codes)
    if not roles:
        raise ValueError("platform roles must not be empty")
    crm_role = min((CRM_BASE_ROLE[r] for r in roles), key=_CRM_RANK.index)
    erp_roles = {c for r in roles for c in ERP_ROLE_CODES[r]}
    extra = {p for r in roles for p in ERP_EXTRA_PERMISSIONS[r]}
    return DerivedAccess(
        crm_role=crm_role,
        platform_access=("crm", "erp"),
        erp_role_codes=tuple(c for c in ERP_CATALOG_ROLE_CODES if c in erp_roles),
        erp_extra_permissions=tuple(p for p in ERP_PERMISSIONS if p in extra),
    )


def erp_access_for(codes: Iterable[str]) -> ErpAccess:
    """Роль и права провижининга ERP: `admin` CRM — суперпользователь, иначе `backoffice`
    с правами `erp_extra_permissions` поверх системных ролей (`role_codes`)."""
    derived = derive_access(codes)
    if derived.crm_role == "admin":
        return ErpAccess("admin", ERP_PERMISSIONS)
    return ErpAccess("backoffice", derived.erp_extra_permissions)
