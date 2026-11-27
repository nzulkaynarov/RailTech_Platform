"""«Что может человек» (ДОСТ-1): сегодняшние права сотрудника словами по ходу сделки. Только чтение.

Каталог — `app/capabilities_generated.py` из `packages/contracts/platform-capabilities.yaml`.
Здесь — расчёт «действие включено»: он не выдаёт и не проверяет права, а повторяет то, что
бэкенды разрешают сегодня. Действие включено, если выполнено всё сразу:
(1) условия BFF «раздел: уровень» по объединению ролей (`app.rbac.allows` — та самая проверка,
что стоит на маршрутах); (2) коды CRM, ERP и EDS, которые CRM вычисляет из тех же разделов
(накопление `full ⊇ read`, как в `platform_roles._accumulated`); (3) поля с ограничением;
(4) для «исключительных действий» — суперпользователь ERP.

Суперпользователь ERP сегодня — держатель системной роли с кодом `ADMIN` (аудит 2026-11-27, К1):
ERP отдаёт ему все коды. Код роли нужен только для показа и живёт здесь одной константой;
расчёт доступа в BFF от него не зависит.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from app.capabilities_generated import DATA
from app.rbac import RoleMatrix, allows, fields_of, merge

CapLevel = Literal["none", "view", "work", "decide"]
LEVEL_ORDER: Final[tuple[str, ...]] = ("none", "view", "work", "decide")
_RANK: Final[dict[str, int]] = {name: index for index, name in enumerate(LEVEL_ORDER)}
ERP_SUPERUSER_ROLE_CODE: Final = "ADMIN"
BACKENDS: Final = ("crm", "erp", "eds")

CAPABILITIES: Final[list[dict[str, Any]]] = DATA["capabilities"]
GROUPS: Final[list[dict[str, Any]]] = DATA["groups"]
FREE_FOR_ALL: Final[dict[str, str]] = DATA["free_for_all"]
SECTION_CODES: Final[dict[str, dict[str, dict[str, list[str]]]]] = DATA["section_codes"]
FIELD_ERP: Final[dict[str, list[str]]] = DATA["field_erp"]
ERP_ALL: Final[frozenset[str]] = frozenset(DATA["erp_all"])


@dataclass(frozen=True)
class Held:
    """Что сотрудник имеет сегодня: разделы, поля и коды бэкендов по объединению ролей."""

    access: Mapping[str, str]
    fields: frozenset[str]
    codes: Mapping[str, frozenset[str]]
    erp_superuser: bool


def codes_of(access: Mapping[str, str], fields: Iterable[str], *, superuser: bool) -> Held:
    """Коды бэкендов по матрице и полям — как их выдаёт CRM."""
    codes: dict[str, set[str]] = {backend: set() for backend in BACKENDS}
    for resource, level in access.items():
        for backend, per_level in SECTION_CODES.get(resource, {}).items():
            codes[backend].update(per_level.get(level, ()))
    held_fields = frozenset(fields)
    for name in held_fields:
        codes["erp"].update(FIELD_ERP.get(name, ()))
    if superuser:
        codes["erp"].update(ERP_ALL)
    return Held(
        access=dict(access),
        fields=held_fields,
        codes={b: frozenset(c) for b, c in codes.items()},
        erp_superuser=superuser,
    )


def held_by(roles: Sequence[RoleMatrix]) -> Held:
    """Объединение ролей сотрудника (максимум по разделу, поля объединяются)."""
    superuser = any(
        getattr(role, "system", False) and getattr(role, "code", None) == ERP_SUPERUSER_ROLE_CODE
        for role in roles
    )
    return codes_of(merge(roles), fields_of(roles), superuser=superuser)


def _gate_ok(access: Mapping[str, str], gate: str) -> bool:
    for alternative in gate.split("|"):
        resource, _, level = alternative.partition(":")
        if allows(access, resource, "full" if level == "full" else "read"):
            return True
    return False


def action_on(action: Mapping[str, Any], held: Held) -> bool:
    """Действие включено: условия BFF, коды бэкендов, поля и суперпользователь — всё сразу."""
    if not all(_gate_ok(held.access, gate) for gate in action["gates"]):
        return False
    if not set(action.get("fields", ())) <= held.fields:
        return False
    if action.get("erp_superuser") and not held.erp_superuser:
        return False
    return all(set(action.get(backend, ())) <= held.codes[backend] for backend in BACKENDS)


@dataclass
class RowState:
    """Строка каталога у одного сотрудника: уровень, «не всё» и включённость каждого действия."""

    key: str
    level: CapLevel
    partial: bool
    on: dict[str, bool] = field(default_factory=dict)


def evaluate(held: Held) -> dict[str, RowState]:
    """Строки каталога по тому, что есть у сотрудника."""
    result: dict[str, RowState] = {}
    for cap in CAPABILITIES:
        on: dict[str, bool] = {}
        top: CapLevel = "none"
        for level in cap["levels"]:
            for action in level["actions"]:
                state = action_on(action, held)
                on[action["key"]] = state
                if state and _RANK[level["level"]] > _RANK[top]:
                    top = level["level"]
        # «Не всё»: у человека есть строка, но выключено хоть одно действие этого и нижних уровней.
        partial = top != "none" and any(
            not on[action["key"]]
            for level in cap["levels"]
            if _RANK[level["level"]] <= _RANK[top]
            for action in level["actions"]
        )
        result[cap["key"]] = RowState(cap["key"], top, partial, on)
    return result


def at_least(level: str, wanted: str) -> bool:
    return _RANK[level] >= _RANK[wanted]


# --- итог словами ------------------------------------------------------------------------

LANGS: Final = ("ru", "uz", "en")
_MAX_LACKS = 6
_LACKS_MORE = {"ru": "и ещё {n}", "uz": "va yana {n} ta", "en": "and {n} more"}
_SEP = dict.fromkeys(LANGS, ", ")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


@dataclass(frozen=True)
class Summary:
    does: dict[str, str] | None
    decides: dict[str, str] | None
    lacks: dict[str, str] | None


def summarize(states: Mapping[str, RowState]) -> Summary:
    """Фразы из текстов каталога: что делает, что решает, чего не может. Без модели."""
    does: dict[str, list[str]] = {lang: [] for lang in LANGS}
    decides: dict[str, list[str]] = {lang: [] for lang in LANGS}
    lacks: dict[str, list[str]] = {lang: [] for lang in LANGS}
    for cap in CAPABILITIES:
        state = states[cap["key"]]
        name = cap["name"]
        if state.level in ("work", "decide") and cap["key"] != "exceptional":
            for lang in LANGS:
                does[lang].append(_lower_first(name[lang]))
        if state.level == "decide":
            for level in cap["levels"]:
                if level["level"] != "decide":
                    continue
                for action in level["actions"]:
                    if state.on.get(action["key"]):
                        for lang in LANGS:
                            decides[lang].append(action["text"][lang])
        if state.level == "none":
            for lang in LANGS:
                lacks[lang].append(_lower_first(name[lang]))
    return Summary(
        does=_join(does),
        decides=_join(decides),
        lacks=_join(lacks, limit=_MAX_LACKS),
    )


def _join(parts: Mapping[str, list[str]], limit: int | None = None) -> dict[str, str] | None:
    if not parts["ru"]:
        return None
    out: dict[str, str] = {}
    for lang in LANGS:
        items = parts[lang]
        extra = ""
        if limit is not None and len(items) > limit:
            extra = f" {_LACKS_MORE[lang].format(n=len(items) - limit)}"
            items = items[:limit]
        out[lang] = _SEP[lang].join(items) + extra
    return out
