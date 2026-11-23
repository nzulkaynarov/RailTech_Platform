"""Реестр зон ответственности: проблемы зоны — чистая функция по фактам (ЕВ-З).

Статус не хранится: «нет ответственного», «ответственный не активен», «срок вышел», «у
ответственного нет прав зоны» считаются из записи зоны, сотрудников и их прав на момент запроса.
Нехватка прав — лишь предупреждение (`warning`), остальное — проблема (`problem`).
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

Severity = Literal["problem", "warning"]

NO_RESPONSIBLE: Final = "no_responsible"
RESPONSIBLE_LACKS_PERMISSIONS: Final = "responsible_lacks_permissions"
RESPONSIBLE_INACTIVE: Final = "responsible_inactive"
DEPUTY_INACTIVE: Final = "deputy_inactive"
TERM_EXPIRED: Final = "term_expired"

_RANK: Final = {"read": 1, "full": 2}


@dataclass(frozen=True, slots=True)
class ZoneProblem:
    code: str
    severity: Severity
    # Разделы, которых не хватает ответственному (только для `responsible_lacks_permissions`).
    sections: tuple[str, ...] = ()


def missing_sections(sections: Collection[str], access: Mapping[str, str]) -> tuple[str, ...]:
    """Разделы зоны, которых у сотрудника нет даже на чтение; порядок — как в зоне."""
    return tuple(s for s in sections if _RANK.get(access.get(s, ""), 0) < _RANK["read"])


def zone_problems(
    *,
    is_active: bool,
    sections: Collection[str],
    responsible_id: int | None,
    deputy_id: int | None,
    valid_to: date | None,
    today: date,
    active_users: Collection[int],
    access_of: Mapping[int, Mapping[str, str]],
) -> list[ZoneProblem]:
    """Проблемы зоны; у выключенной зоны их нет. `active_users` — id действующих сотрудников."""
    if not is_active:
        return []
    problems: list[ZoneProblem] = []
    if responsible_id is None:
        problems.append(ZoneProblem(NO_RESPONSIBLE, "problem"))
    elif responsible_id not in active_users:
        problems.append(ZoneProblem(RESPONSIBLE_INACTIVE, "problem"))
    else:
        lacking = missing_sections(sections, access_of.get(responsible_id, {}))
        if lacking:
            problems.append(ZoneProblem(RESPONSIBLE_LACKS_PERMISSIONS, "warning", lacking))
    if deputy_id is not None and deputy_id not in active_users:
        problems.append(ZoneProblem(DEPUTY_INACTIVE, "problem"))
    if valid_to is not None and valid_to < today:
        problems.append(ZoneProblem(TERM_EXPIRED, "problem"))
    return problems
