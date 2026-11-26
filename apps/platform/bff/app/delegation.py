"""Делегирование (СОТР-2): «что делегировано» человеку — список действий вместо ролей.

Действия — данные (`capabilities_generated.py` из `packages/contracts/platform-rbac-
capabilities.yaml`):
глагол, область и разделы каталога с уровнем. Права по-прежнему живут в ролях CRM, поэтому
личный набор человека —
служебная роль CRM «личный набор» (описание `personal:<id сотрудника>`), которую собирает этот
модуль; обычные роли
остаются заготовками «набор по должности». Чистые функции, без I/O.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from app.capabilities_generated import AREAS, CAPABILITIES

PERSONAL_PREFIX: Final = "personal:"
_RANK: Final[dict[str, int]] = {"read": 1, "full": 2}
_BY_CODE: Final = {str(c["code"]): c for c in CAPABILITIES}
# Разделы, которыми распоряжаются действия: остальные при сохранении переносятся без изменений.
COVERED: Final = frozenset(key for c in CAPABILITIES for key in c["grants"])


def personal_marker(user_id: str) -> str:
    return f"{PERSONAL_PREFIX}{user_id}"


def is_personal(role: Mapping[str, Any]) -> bool:
    return str(role.get("description") or "").startswith(PERSONAL_PREFIX)


def known(codes: Iterable[str]) -> list[str]:
    """Коды в порядке каталога; неизвестный — `ValueError`."""
    wanted = set(codes)
    unknown = sorted(wanted - _BY_CODE.keys())
    if unknown:
        raise ValueError(f"неизвестные действия: {unknown}")
    return [code for code in _BY_CODE if code in wanted]


def merge_access(roles: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Объединение матриц ролей: максимум по разделу."""
    merged: dict[str, str] = {}
    for role in roles:
        for key, level in (role.get("access") or {}).items():
            if _RANK.get(level, 0) > _RANK.get(merged.get(key, ""), 0):
                merged[key] = level
    return merged


def merge_fields(roles: Iterable[Mapping[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for role in roles:
        for field in role.get("restricted_fields") or []:
            seen.setdefault(str(field))
    return list(seen)


def codes_on(access: Mapping[str, str]) -> list[str]:
    """Действие включено, если все его разделы у человека на нужном уровне или выше."""
    return [
        str(c["code"])
        for c in CAPABILITIES
        if all(_RANK.get(access.get(k, ""), 0) >= _RANK[lvl] for k, lvl in c["grants"].items())
    ]


def compose(codes: Sequence[str], base: Mapping[str, str]) -> dict[str, str]:
    """Матрица личного набора: разделы выбранных действий + разделы вне каталога действий."""
    access: dict[str, str] = {k: v for k, v in base.items() if k not in COVERED}
    for code in known(codes):
        for key, level in _BY_CODE[code]["grants"].items():
            if _RANK[level] > _RANK.get(access.get(key, ""), 0):
                access[key] = level
    return access


def exceeds(
    new: Mapping[str, str], before: Mapping[str, str], granter: Mapping[str, str]
) -> list[str]:
    """Разделы, где новый уровень выше и прежнего, и уровня самого выдающего."""
    return sorted(
        key
        for key, level in new.items()
        if _RANK[level] > _RANK.get(before.get(key, ""), 0)
        and _RANK[level] > _RANK.get(granter.get(key, ""), 0)
    )


def catalog() -> dict[str, Any]:
    return {
        "areas": [{"code": code, "label": dict(label)} for code, label in AREAS.items()],
        "capabilities": [
            {"code": c["code"], "area": c["area"], "label": dict(c["label"])} for c in CAPABILITIES
        ],
    }


def suggest_preset(position: str | None, presets: Sequence[Mapping[str, Any]]) -> str | None:
    """Набор по должности: роль с тем же названием (без регистра); нет такой — `None`."""
    needle = (position or "").strip().casefold()
    if not needle:
        return None
    for preset in presets:
        if str(preset["name"]).strip().casefold() == needle:
            return str(preset["id"])
    return None
