"""Роли Платформы для тестов: как их отдаёт CRM в `/me` (`platform_role_refs` с матрицами, R-1/R-2).

Шесть предустановок каталога (системные и шаблоны) получают постоянные id; созданную роль
описывает `custom`. Матрицы — из эталона `rbac_oracle` (не из сгенерированного каталога).
"""

from typing import Any

from tests.rbac_oracle import FIELDS, ROLES, SYSTEM, access_of

ROLE_IDS: dict[str, int] = {code: index + 1 for index, code in enumerate(ROLES)}
NAMES: dict[str, str] = {
    "ADMIN": "Администратор",
    "DIRECTOR": "Директор",
    "MANAGER": "Менеджер",
    "SUPPLY": "Снабженец",
    "ENGINEER": "Гл. инженер",
    "ACCOUNTANT": "Бухгалтер",
}

Role = str | dict[str, Any]


def ref(role: Role) -> dict[str, Any]:
    """Роль `/me` CRM: код предустановки (`MANAGER`) или готовая запись (`custom`)."""
    if isinstance(role, dict):
        return role
    return {
        "id": ROLE_IDS[role],
        "name": NAMES[role],
        "system": role in SYSTEM,
        "code": role if role in SYSTEM else f"tpl:{role}",
        "access": access_of(role),
        "restricted_fields": list(FIELDS[role]),
    }


def refs(roles: list[Role]) -> list[dict[str, Any]]:
    return [ref(r) for r in roles]


def custom(
    role_id: int, name: str, access: dict[str, str], fields: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Роль, созданная администратором: без кода, матрица — данные."""
    return {
        "id": role_id,
        "name": name,
        "system": False,
        "code": None,
        "access": access,
        "restricted_fields": list(fields),
    }


def rid(code: str) -> str:
    """Id предустановки строкой (как в контракте BFF)."""
    return str(ROLE_IDS[code])
