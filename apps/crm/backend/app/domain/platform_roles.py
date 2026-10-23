"""Роли Платформы как данные: вычисление прав по каталогу (ADR-0012, CRM-01 → R-1).

Каталог возможностей — сгенерированный из `packages/contracts/platform-rbac.yaml` модуль
`platform_roles_generated.py`; здесь правила поверх него (чистые функции, без I/O):

- роль = матрица `access` (раздел -> `full|read`, скрытые не хранятся) и `restricted_fields`;
- права сотрудника = объединение его ролей: максимум по разделу и объединение полей;
- права CRM (casbin) и ERP (`Permission`) вычисляются из каталога по разделу и уровню (уровень
  `full` включает `read`); поле с ограничением открывает права ERP из каталога;
- базовая роль CRM `admin|manager|viewer` остаётся для старого фронта до T4: роль с кодом — как
  в версии 1 (`CRM_BASE_ROLE_BY_CODE`), роль без кода — по `CRM_BASE_ROLE_BY_ACCESS`; у сотрудника
  берётся старшая (admin > manager > viewer);
- провижининг ERP: `permissions` = вычисленный набор, `role_codes = []`; администратор CRM
  (`admin`) остаётся суперпользователем ERP.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from app.domain.erp_permissions import ERP_PERMISSIONS, ErpAccess
from app.domain.platform_roles_generated import (
    CRM_BACKEND,
    CRM_BASE_ROLE_BY_ACCESS,
    CRM_BASE_ROLE_BY_CODE,
    ERP_BACKEND,
    FIELD_ERP_BACKEND,
    RESOURCE_KEYS,
    RESOURCE_LEVELS,
    ROLE_ACCESS,
    ROLE_NAMES,
    ROLE_RESTRICTED_FIELDS,
    SYSTEM_ROLE_CODES,
    TEMPLATE_ROLE_CODES,
)

__all__ = [
    "LEGACY_ROLE_CODES",
    "POLICY_DOMAIN",
    "SUBJECT_PREFIX",
    "TEMPLATE_PREFIX",
    "AccessDiff",
    "DerivedAccess",
    "RoleGrant",
    "check_spec",
    "crm_policies",
    "default_roles",
    "derive_access",
    "diff_access",
    "erp_access_for",
    "erp_permissions_for",
    "legacy_code",
    "merge_access",
    "normalize_position",
    "role_code_for",
    "role_subject",
]

Level = Literal["full", "read"]

POSITION_MAX_LEN: Final = 120
TEMPLATE_PREFIX: Final = "tpl:"
SUBJECT_PREFIX: Final = "pr:"
POLICY_DOMAIN: Final = "crm"
# Коды ролей каталога без префикса `tpl:` (порядок MANAGER, DIRECTOR, SUPPLY, ENGINEER, ACCOUNTANT,
# ADMIN); публичного поля с кодами в API больше нет (удалено в R-1b).
LEGACY_ROLE_CODES: Final[tuple[str, ...]] = tuple(CRM_BASE_ROLE_BY_CODE)
_LEVEL_RANK: Final[dict[str, int]] = {"read": 1, "full": 2}
# Старшинство базовых ролей CRM при нескольких ролях.
_CRM_RANK: Final[tuple[str, ...]] = ("admin", "manager", "viewer")


@dataclass(frozen=True, slots=True)
class RoleGrant:
    """Что роль даёт сотруднику: код (если есть), матрица и поля с ограничением."""

    access: Mapping[str, str]
    restricted_fields: Sequence[str] = ()
    code: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedAccess:
    """Что вычисляется из набора ролей Платформы сотрудника."""

    crm_role: str
    platform_access: tuple[str, ...]
    erp_role_codes: tuple[str, ...]
    erp_permissions: tuple[str, ...]
    access: Mapping[str, str]
    restricted_fields: tuple[str, ...]
    crm_permissions: frozenset[tuple[str, str]]


# --- коды и субъекты ---------------------------------------------------------------------------


def role_code_for(legacy: str) -> str:
    """Код роли в `platform_roles.code` по старому коду: системные как есть, шаблоны `tpl:<код>`."""
    return legacy if legacy in SYSTEM_ROLE_CODES else TEMPLATE_PREFIX + legacy


def legacy_code(code: str | None) -> str | None:
    """Старый код (`MANAGER`, `ADMIN`, ...) по коду роли; у созданных администратором — `None`."""
    if code is None:
        return None
    legacy = code.removeprefix(TEMPLATE_PREFIX) if code.startswith(TEMPLATE_PREFIX) else code
    in_catalog = legacy in TEMPLATE_ROLE_CODES or legacy in SYSTEM_ROLE_CODES
    return legacy if in_catalog and role_code_for(legacy) == code else None


def role_subject(role_id: int) -> str:
    """Субъект casbin роли Платформы."""
    return f"{SUBJECT_PREFIX}{role_id}"


def normalize_position(value: str | None) -> str | None:
    """Должность (SPEC-v3 §4.3): обрезанный текст ≤ 120 символов; пусто — `None`."""
    text = (value or "").strip()
    if len(text) > POSITION_MAX_LEN:
        raise ValueError(f"position is longer than {POSITION_MAX_LEN} characters")
    return text or None


def default_roles() -> list[dict[str, object]]:
    """Системные роли и шаблоны каталога строками `platform_roles` (тесты, сверка миграции)."""
    rows: list[dict[str, object]] = []
    for code in (*SYSTEM_ROLE_CODES, *TEMPLATE_ROLE_CODES):
        rows.append(
            {
                "code": role_code_for(code),
                "name": ROLE_NAMES[code]["ru"],
                "is_system": code in SYSTEM_ROLE_CODES,
                "access": dict(ROLE_ACCESS[code]),
                "restricted_fields": list(ROLE_RESTRICTED_FIELDS[code]),
            }
        )
    return rows


# --- проверка черновика роли -------------------------------------------------------------------


def check_spec(
    access: Mapping[str, str], restricted_fields: Iterable[str]
) -> tuple[dict[str, str], list[str]]:
    """Матрица и поля роли в каноническом виде; неизвестный раздел или уровень вне `levels`
    раздела, неизвестное поле — `ValueError` (422)."""
    for resource, level in access.items():
        if resource not in RESOURCE_LEVELS:
            raise ValueError(f"unknown resource: {resource}")
        if level not in RESOURCE_LEVELS[resource]:
            raise ValueError(f"level {level!r} is not allowed for {resource}")
    fields = set(restricted_fields)
    unknown = fields - set(FIELD_ERP_BACKEND)
    if unknown:
        raise ValueError(f"unknown restricted fields: {sorted(unknown)}")
    return (
        {key: access[key] for key in RESOURCE_KEYS if key in access},
        [name for name in FIELD_ERP_BACKEND if name in fields],
    )


# --- объединение и вычисление ------------------------------------------------------------------


def merge_access(grants: Iterable[RoleGrant]) -> dict[str, str]:
    """Объединение матриц: максимум по разделу (full > read), порядок каталога."""
    merged: dict[str, str] = {}
    for grant in grants:
        for resource, level in grant.access.items():
            if _LEVEL_RANK.get(level, 0) > _LEVEL_RANK.get(merged.get(resource, ""), 0):
                merged[resource] = level
    return {key: merged[key] for key in RESOURCE_KEYS if key in merged}


def _merge_fields(grants: Iterable[RoleGrant]) -> tuple[str, ...]:
    held = {name for grant in grants for name in grant.restricted_fields}
    return tuple(name for name in FIELD_ERP_BACKEND if name in held)


def _accumulated(
    table: Mapping[str, Mapping[str, tuple[str, ...]]], resource: str, level: str
) -> list[str]:
    """Права раздела на уровне: объединение списков уровней не выше заданного (full ⊇ read)."""
    rows = table.get(resource, {})
    return [
        perm
        for lv, perms in rows.items()
        if _LEVEL_RANK[lv] <= _LEVEL_RANK[level]
        for perm in perms
    ]


def crm_policies(access: Mapping[str, str]) -> frozenset[tuple[str, str]]:
    """Права CRM `(ресурс, действие)` по матрице: `leads:read` -> `("leads", "read")`."""
    pairs: set[tuple[str, str]] = set()
    for resource, level in access.items():
        for perm in _accumulated(CRM_BACKEND, resource, level):
            res, _, action = perm.partition(":")
            pairs.add((res, action))
    return frozenset(pairs)


def erp_permissions_for(access: Mapping[str, str], fields: Iterable[str]) -> tuple[str, ...]:
    """Права ERP по матрице и полям с ограничением, в порядке каталога ERP."""
    granted = {
        p for resource, level in access.items() for p in _accumulated(ERP_BACKEND, resource, level)
    }
    granted |= {p for name in fields for p in FIELD_ERP_BACKEND.get(name, ())}
    return tuple(p for p in ERP_PERMISSIONS if p in granted)


def _meets(access: Mapping[str, str], condition: str) -> bool:
    resource, _, level = condition.partition(":")
    return _LEVEL_RANK.get(access.get(resource, ""), 0) >= _LEVEL_RANK[level]


def role_crm_base(grant: RoleGrant) -> str:
    """Базовая роль CRM одной роли для старого фронта (до T4)."""
    legacy = legacy_code(grant.code)
    if legacy is not None:
        return CRM_BASE_ROLE_BY_CODE[legacy]
    for role in ("admin", "manager"):
        if any(_meets(grant.access, c) for c in CRM_BASE_ROLE_BY_ACCESS.get(role, ())):
            return role
    return "viewer"


def derive_access(grants: Iterable[RoleGrant]) -> DerivedAccess:
    """Доступ по непустому набору ролей Платформы: объединение матриц и полей."""
    roles = list(grants)
    if not roles:
        raise ValueError("platform roles must not be empty")
    access = merge_access(roles)
    fields = _merge_fields(roles)
    return DerivedAccess(
        crm_role=min((role_crm_base(r) for r in roles), key=_CRM_RANK.index),
        platform_access=("crm", "erp"),
        erp_role_codes=(),
        erp_permissions=erp_permissions_for(access, fields),
        access=access,
        restricted_fields=fields,
        crm_permissions=crm_policies(access),
    )


def erp_access_for(grants: Iterable[RoleGrant]) -> ErpAccess:
    """Роль и права провижининга ERP: `admin` CRM — суперпользователь, иначе `backoffice`
    с вычисленными `permissions` (`role_codes` пусты)."""
    derived = derive_access(grants)
    if derived.crm_role == "admin":
        return ErpAccess("admin", ERP_PERMISSIONS)
    return ErpAccess("backoffice", derived.erp_permissions)


# --- последствия изменения (preview) -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessDiff:
    """Разница матриц: разделы `(раздел, уровень)` и поля с ограничением."""

    gained: list[tuple[str, str]]
    lost: list[tuple[str, str]]
    fields_gained: list[str]
    fields_lost: list[str]


def diff_access(
    before: Mapping[str, str],
    after: Mapping[str, str],
    before_fields: Iterable[str] = (),
    after_fields: Iterable[str] = (),
) -> AccessDiff:
    """Что сотрудник получит и потеряет.

    Получит — раздел впервые или с более высоким уровнем (уровень «после»); потеряет — раздел
    пропал или уровень снижен (уровень «до»)."""
    gained: list[tuple[str, str]] = []
    lost: list[tuple[str, str]] = []
    for resource in RESOURCE_KEYS:
        was = _LEVEL_RANK.get(before.get(resource, ""), 0)
        now = _LEVEL_RANK.get(after.get(resource, ""), 0)
        if now > was:
            gained.append((resource, after[resource]))
        elif now < was:
            lost.append((resource, before[resource]))
    held_before, held_after = set(before_fields), set(after_fields)
    return AccessDiff(
        gained=gained,
        lost=lost,
        fields_gained=[f for f in FIELD_ERP_BACKEND if f in held_after - held_before],
        fields_lost=[f for f in FIELD_ERP_BACKEND if f in held_before - held_after],
    )
