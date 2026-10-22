"""Доступ к разделам по матрице Платформы (SPEC-v3 §4.2, 02-architecture.md §6).

Данные — `app/rbac_generated.py` (из packages/contracts/platform-rbac.yaml); здесь только логика.
Два режима расчёта (Q-PLT-12-1, контракт BFF 0.2.2):

- **права операций** (`allows`, `require` в `app/deps.py`) считаются по объединению всех ролей
  сотрудника: максимум по ролям (full > read > hidden); активная роль их не меняет;
- **вид** (`modules_for`, `resources_for`, `restricted_fields_for` для `Me`) считается по активной
  роли, если она задана, иначе по объединению (`view_roles`).

Решение о праве на операцию остаётся за CRM и ERP; матрица — видимость и маршруты.
"""

from collections.abc import Collection, Iterable, Mapping
from typing import Any, Literal

from app.rbac_generated import (
    ACCESS,
    MENU,
    MODULES,
    RESOURCE_MODULE,
    RESTRICTED_FIELDS,
    ROLES,
    Level,
    ModuleCode,
    RoleCode,
)

Need = Literal["read", "full"]
_RANK: dict[str, int] = {"hidden": 0, "read": 1, "full": 2}


def known_roles(codes: Iterable[str]) -> list[RoleCode]:
    """Только роли контракта, без повторов, в порядке контракта (чужие коды CRM отбрасываются)."""
    wanted = set(codes)
    return [r for r in ROLES if r in wanted]


def level_for(roles: Collection[str], resource: str) -> Level:
    """Максимальный уровень раздела по набору ролей; неизвестный раздел — KeyError."""
    row = ACCESS[resource]
    best: Level = "hidden"
    for role in known_roles(roles):
        level = row[role]
        if _RANK[level] > _RANK[best]:
            best = level
    return best


def allows(roles: Collection[str], resource: str, need: Need = "read") -> bool:
    """Роли дают не меньше `need` в разделе (`read` — чтение, `full` — изменение)."""
    return _RANK[level_for(roles, resource)] >= _RANK[need]


def view_roles(roles: Collection[str], active_role: str | None) -> list[RoleCode]:
    """Роли «вида»: активная одна, если задана и есть у сотрудника, иначе все."""
    owned = known_roles(roles)
    if active_role is not None and active_role in owned:
        return [r for r in owned if r == active_role]
    return owned


def resources_for(roles: Collection[str]) -> dict[str, Literal["full", "read"]]:
    """Разделы матрицы, видимые набору ролей, с уровнем; скрытые не перечисляются."""
    result: dict[str, Literal["full", "read"]] = {}
    for key in ACCESS:
        level = level_for(roles, key)
        if level != "hidden":
            result[key] = level
    return result


def modules_for(roles: Collection[str]) -> list[ModuleCode]:
    """Модули рейла в порядке показа: виден хотя бы один раздел модуля."""
    visible = {RESOURCE_MODULE[k] for k in resources_for(roles)}
    return [m for m in MODULES if m in visible]


def menu_for(roles: Collection[str]) -> dict[ModuleCode, list[str]]:
    """Видимые пункты меню по модулям: хотя бы один раздел пункта (`any_of`) не скрыт."""
    visible = resources_for(roles)
    return {
        module: [item for item, sections in items.items() if any(s in visible for s in sections)]
        for module, items in MENU.items()
    }


def restricted_fields_for(roles: Collection[str]) -> list[str]:
    """Группы полей с ограничением, видимые хотя бы одной из ролей."""
    owned = set(known_roles(roles))
    return [name for name, visible_to in RESTRICTED_FIELDS.items() if owned & set(visible_to)]


def strip_restricted(
    payload: Any, roles: Collection[str], rules: Mapping[str, Collection[str]]
) -> Any:
    """Вырезать из ответа поля групп, которых не видит ни одна роль сотрудника.

    `rules` — какие ключи ответа относятся к какой группе (`{"cost_margin": ("cost", "margin")}`):
    их задаёт экран, который отдаёт такие поля. Работает рекурсивно по словарям и спискам и
    возвращает копию. Вырезание идёт по объединению ролей — как и права операций; активная роль
    («вид») скрывает поля только в SPA через `Me.restricted_fields`.
    """
    unknown = [group for group in rules if group not in RESTRICTED_FIELDS]
    if unknown:
        raise ValueError(f"нет такой группы полей с ограничением: {unknown}")
    visible = set(restricted_fields_for(roles))
    hidden_keys = {key for group, keys in rules.items() if group not in visible for key in keys}
    return _strip(payload, hidden_keys)


def _strip(node: Any, hidden_keys: set[str]) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v, hidden_keys) for k, v in node.items() if k not in hidden_keys}
    if isinstance(node, list):
        return [_strip(item, hidden_keys) for item in node]
    return node
