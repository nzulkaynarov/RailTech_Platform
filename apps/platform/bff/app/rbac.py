"""Доступ к разделам по ролям сотрудника (ADR-0012, 02-architecture.md §6).

Роли — данные CRM: у каждой роли сотрудника есть матрица (раздел каталога -> `full|read`) и поля с
ограничением; CRM отдаёт их в `/me` (`platform_role_refs`), у системных ролей — матрицу каталога.
Каталог (разделы, меню, поля, виды очереди) — `app/rbac_generated.py` из
`packages/contracts/platform-rbac.yaml`; здесь только логика. Коды ролей здесь не встречаются.

Два режима расчёта (Q-PLT-12-1, контракт BFF 0.2.2 и 0.3.0):

- **права операций** (`allows`, `require` в `app/deps.py`) — по объединению всех ролей сотрудника:
  максимум по разделу (full > read); активная роль их не меняет;
- **вид** (`View`: модули, разделы, поля, «Моя очередь») — по активной роли, если она задана,
  иначе по объединению.

Решение о праве на операцию остаётся за CRM и ERP; каталог — видимость и маршруты.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.rbac_generated import (
    MENU,
    MODULES,
    QUEUE,
    RESOURCE_BACKENDS,
    RESOURCE_LEVELS,
    RESOURCE_MODULE,
    RESTRICTED_FIELDS,
    Level,
    ModuleCode,
)

Need = Literal["read", "full"]
Access = dict[str, Level]
_RANK: dict[str, int] = {"read": 1, "full": 2}


class RoleMatrix(Protocol):
    """Роль сотрудника: id, матрица и поля с ограничением (снимок `/me` CRM в сессии)."""

    @property
    def id(self) -> int: ...

    @property
    def access(self) -> Mapping[str, str]: ...

    @property
    def restricted_fields(self) -> Sequence[str]: ...


def clean_access(raw: Mapping[str, Any]) -> Access:
    """Матрица в порядке каталога: только известные разделы и допустимые для них уровни."""
    result: Access = {}
    for key, levels in RESOURCE_LEVELS.items():
        level = raw.get(key)
        if level in levels:
            result[key] = level
    return result


def merge(roles: Iterable[RoleMatrix]) -> Access:
    """Объединение матриц ролей: максимум по разделу (full > read), порядок каталога."""
    best: dict[str, Level] = {}
    for role in roles:
        for key, level in clean_access(role.access).items():
            if _RANK[level] > _RANK.get(best.get(key, ""), 0):
                best[key] = level
    return {key: best[key] for key in RESOURCE_MODULE if key in best}


def fields_of(roles: Iterable[RoleMatrix]) -> list[str]:
    """Поля с ограничением, которые видит хотя бы одна роль (порядок каталога)."""
    held = {name for role in roles for name in role.restricted_fields}
    return [name for name in RESTRICTED_FIELDS if name in held]


def level_for(access: Mapping[str, str], resource: str) -> Level | None:
    """Уровень раздела в матрице (`None` — скрыт); неизвестный раздел — KeyError."""
    if resource not in RESOURCE_MODULE:
        raise KeyError(resource)
    level = access.get(resource)
    return level if level in ("full", "read") else None  # type: ignore[return-value]


def allows(access: Mapping[str, str], resource: str, need: Need = "read") -> bool:
    """Матрица даёт не меньше `need` в разделе (`read` — чтение, `full` — изменение)."""
    level = level_for(access, resource)
    return level is not None and _RANK[level] >= _RANK[need]


def modules_for(access: Mapping[str, str]) -> list[ModuleCode]:
    """Модули рейла в порядке показа: виден хотя бы один пункт меню модуля.

    Разделы-возможности без своего пункта меню (виза расчёта по товарам или услугам) модуль не
    открывают: иначе в рейле был бы модуль с пустым подменю.
    """
    menu = menu_for(access)
    return [m for m in MODULES if menu.get(m)]


def menu_for(access: Mapping[str, str]) -> dict[ModuleCode, list[str]]:
    """Видимые пункты меню по модулям: виден хотя бы один раздел пункта (`any_of`)."""
    return {
        module: [item for item, sections in items.items() if any(s in access for s in sections)]
        for module, items in MENU.items()
    }


def queue_kinds(access: Mapping[str, str]) -> list[str]:
    """Виды работы «Моей очереди», которые дают разделы матрицы (секция `queue` каталога)."""
    return [kind for kind, (resource, level) in QUEUE.items() if allows(access, resource, level)]


def gives_backend(access: Mapping[str, str], backend: Literal["crm", "erp"]) -> bool:
    """Хотя бы один раздел матрицы даёт права в бэкенде (по `backend` каталога)."""
    return any(backend in RESOURCE_BACKENDS.get(key, ()) for key in access)


@dataclass(frozen=True)
class View:
    """«Вид»: роли, по которым считаются модули, разделы, поля и очередь, и их объединение."""

    roles: tuple[RoleMatrix, ...]
    access: Access
    fields: tuple[str, ...]

    @classmethod
    def of(cls, roles: Iterable[RoleMatrix]) -> "View":
        held = tuple(roles)
        return cls(held, merge(held), tuple(fields_of(held)))

    @property
    def kinds(self) -> list[str]:
        return queue_kinds(self.access)

    def wants(self, kind: str) -> bool:
        return kind in self.kinds

    def role_for(self, kind: str) -> int | None:
        """Первая роль «вида», которая даёт этот вид работы (её id — `QueueItem.role_id`)."""
        resource, level = QUEUE[kind]
        for role in self.roles:
            if allows(clean_access(role.access), resource, level):
                return role.id
        return None


def view_roles(roles: Sequence[RoleMatrix], active_role: int | None) -> list[RoleMatrix]:
    """Роли «вида»: активная одна, если задана и есть у сотрудника, иначе все."""
    if active_role is not None:
        chosen = [r for r in roles if r.id == active_role]
        if chosen:
            return chosen
    return list(roles)


def strip_restricted(
    payload: Any, visible_fields: Collection[str], rules: Mapping[str, Collection[str]]
) -> Any:
    """Вырезать из ответа поля групп, которых сотрудник не видит.

    `visible_fields` — поля с ограничением по объединению ролей (как права операций; активная роль
    скрывает поля только в SPA через `Me.restricted_fields`). `rules` — какие ключи ответа относятся
    к какой группе (`{"cost_margin": ("cost", "margin")}`): их задаёт экран. Работает рекурсивно по
    словарям и спискам и возвращает копию.
    """
    unknown = [group for group in rules if group not in RESTRICTED_FIELDS]
    if unknown:
        raise ValueError(f"нет такой группы полей с ограничением: {unknown}")
    visible = set(visible_fields)
    hidden_keys = {key for group, keys in rules.items() if group not in visible for key in keys}
    return _strip(payload, hidden_keys)


def _strip(node: Any, hidden_keys: set[str]) -> Any:
    if isinstance(node, dict):
        return {k: _strip(v, hidden_keys) for k, v in node.items() if k not in hidden_keys}
    if isinstance(node, list):
        return [_strip(item, hidden_keys) for item in node]
    return node
