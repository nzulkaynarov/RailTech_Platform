"""Сборка ответов «Что может человек» (ДОСТ-1): карточка, таблица «Кто что может», предупреждения.

Чистые функции без сети: данные (люди, роли, зоны, подпись) приносит `app/api/capabilities.py`.
Права не меняются.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.capabilities import (
    CAPABILITIES,
    FREE_FOR_ALL,
    GROUPS,
    RowState,
    at_least,
    evaluate,
    held_by,
    summarize,
)
from app.schemas import RoleRef
from app.schemas_capabilities import (
    CapabilityAction,
    CapabilityAuthority,
    CapabilityGroup,
    CapabilityLevelActions,
    CapabilityMatrix,
    CapabilityPerson,
    CapabilityRow,
    CapabilitySummary,
    CapabilityText,
    CapabilityWarning,
    CapabilityZone,
    EmployeeCapabilities,
    MatrixCapability,
    MatrixCell,
    MatrixEmployee,
    MatrixGroup,
)
from app.schemas_eds_signing import SigningAuthority
from app.schemas_profile import DeputyPeriod
from app.schemas_zones import ZoneText

OTHERS_MAX = 5
_EXCEPTIONAL = "exceptional"


@dataclass(frozen=True)
class RoleView:
    """Роль для расчёта: то, что нужно `app.rbac`, плюс системная ли она и её код."""

    id: int
    name: str
    system: bool
    code: str | None
    access: Mapping[str, str]
    restricted_fields: Sequence[str]

    def ref(self) -> RoleRef:
        return RoleRef(id=str(self.id), name=self.name, system=self.system, code=self.code)


@dataclass
class Person:
    id: str
    name: str
    initials: str
    position: str | None
    avatar_url: str | None
    roles: list[RoleView]
    deputy: DeputyPeriod | None = None
    states: dict[str, RowState] = field(default_factory=dict)

    def ref(self) -> CapabilityPerson:
        return CapabilityPerson(
            id=self.id,
            name=self.name,
            initials=self.initials,
            position=self.position,
            avatar_url=self.avatar_url,
        )


@dataclass(frozen=True)
class Extras:
    """Подпись и зоны по сотрудникам; `known = False` — читать их было нечем (нет раздела)."""

    signing_known: bool = False
    signing: Mapping[str, list[CapabilityAuthority]] = field(default_factory=dict)
    zones_known: bool = False
    zones: Mapping[str, list[CapabilityZone]] = field(default_factory=dict)


def _text(raw: Mapping[str, str]) -> CapabilityText:
    return CapabilityText(ru=raw["ru"], uz=raw["uz"], en=raw["en"])


def prepare(people: Iterable[Person]) -> list[Person]:
    """Считает строки каталога каждого сотрудника по объединению его ролей."""
    out = list(people)
    for person in out:
        person.states = evaluate(held_by(person.roles))
    return out


def _from_roles(person: Person, cap_key: str) -> list[RoleRef]:
    """Роли, каждая из которых сама по себе даёт этой строке уровень выше «нет»."""
    refs: list[RoleRef] = []
    for role in person.roles:
        if evaluate(held_by([role]))[cap_key].level != "none":
            refs.append(role.ref())
    return refs


def _row(
    cap: Mapping[str, Any], person: Person, everyone: Sequence[Person], *, with_others: bool
) -> CapabilityRow:
    state = person.states[cap["key"]]
    others: list[Person] = []
    if with_others and state.level != "none":
        others = [
            p
            for p in everyone
            if p.id != person.id and at_least(p.states[cap["key"]].level, state.level)
        ]
    return CapabilityRow(
        key=cap["key"],
        group=cap["group"],
        name=_text(cap["name"]),
        level=state.level,
        partial=state.partial,
        levels=[
            CapabilityLevelActions(
                level=level["level"],
                actions=[
                    CapabilityAction(
                        key=a["key"],
                        text=_text(a["text"]),
                        on=state.on[a["key"]],
                        gates=list(a["gates"]),
                    )
                    for a in level["actions"]
                ],
            )
            for level in cap["levels"]
        ],
        from_roles=_from_roles(person, cap["key"]),
        others=[p.ref() for p in others[:OTHERS_MAX]],
        others_total=len(others),
    )


def has_deputy(person: Person, today: date) -> bool:
    return person.deputy is not None and person.deputy.date_to >= today.isoformat()


def warnings(
    everyone: Sequence[Person], extras: Extras, today: date, *, only: str | None = None
) -> list[CapabilityWarning]:
    """«Единственный, кто решает» и «никто не решает». Виза без права подписи — не проблема."""
    found: list[CapabilityWarning] = []
    for cap in CAPABILITIES:
        key = cap["key"]
        if key == _EXCEPTIONAL or not any(lv["level"] == "decide" for lv in cap["levels"]):
            continue
        holders = [p for p in everyone if p.states[key].level == "decide"]
        if not holders:
            if only is None:
                found.append(CapabilityWarning(code="nobody_decides", capability=key))
        elif len(holders) == 1 and (only is None or holders[0].id == only):
            found.append(
                CapabilityWarning(
                    code="only_decider",
                    capability=key,
                    person=holders[0].ref(),
                    has_deputy=has_deputy(holders[0], today),
                )
            )
    return found


def card(
    person: Person,
    everyone: Sequence[Person],
    extras: Extras,
    today: date,
    *,
    with_others: bool = True,
    grantors: list[CapabilityPerson] | None = None,
) -> EmployeeCapabilities:
    """Карточка «Что может этот человек»: итог словами, строки по шагам, подпись, зоны."""
    summary = summarize(person.states)
    by_group: dict[str, list[CapabilityRow]] = {g["key"]: [] for g in GROUPS}
    for cap in CAPABILITIES:
        by_group[cap["group"]].append(_row(cap, person, everyone, with_others=with_others))
    zones = extras.zones.get(person.id, [])
    return EmployeeCapabilities(
        employee=person.ref(),
        roles=[r.ref() for r in person.roles],
        summary=CapabilitySummary(
            does=CapabilityText(**summary.does) if summary.does else None,
            decides=CapabilityText(**summary.decides) if summary.decides else None,
            lacks=CapabilityText(**summary.lacks) if summary.lacks else None,
        ),
        groups=[
            CapabilityGroup(
                key=g["key"], step=_text(g["step"]), name=_text(g["name"]), rows=by_group[g["key"]]
            )
            for g in GROUPS
        ],
        signing_known=extras.signing_known,
        signing=extras.signing.get(person.id, []),
        zones_known=extras.zones_known,
        zones=zones,
        deputy=person.deputy,
        warnings=warnings(everyone, extras, today, only=person.id) if with_others else [],
        free_for_all=_text(FREE_FOR_ALL),
        grantors=grantors,
    )


def matrix(everyone: Sequence[Person], extras: Extras, today: date) -> CapabilityMatrix:
    """Таблица «Кто что может» по действующим сотрудникам."""
    groups = [
        MatrixGroup(
            key=g["key"],
            step=_text(g["step"]),
            name=_text(g["name"]),
            capabilities=[
                MatrixCapability(
                    key=cap["key"],
                    name=_text(cap["name"]),
                    levels=[lv["level"] for lv in cap["levels"]],
                )
                for cap in CAPABILITIES
                if cap["group"] == g["key"]
            ],
        )
        for g in GROUPS
    ]
    return CapabilityMatrix(
        groups=groups,
        employees=[
            MatrixEmployee(
                person=p.ref(),
                roles=[r.ref() for r in p.roles],
                cells={
                    key: MatrixCell(level=s.level, partial=s.partial) for key, s in p.states.items()
                },
                signing=extras.signing.get(p.id, []),
                zones=extras.zones.get(p.id, []),
                deputy=p.deputy,
            )
            for p in everyone
        ],
        signing_known=extras.signing_known,
        zones_known=extras.zones_known,
        warnings=warnings(everyone, extras, today),
        free_for_all=_text(FREE_FOR_ALL),
    )


def zones_by_person(raw_zones: Iterable[Mapping[str, Any]]) -> dict[str, list[CapabilityZone]]:
    """Зоны CRM -> по сотруднику: где он ответственный, замещающий или куратор."""
    out: dict[str, list[CapabilityZone]] = {}
    for zone in raw_zones:
        if not zone.get("is_active", True):
            continue
        for role, key in (
            ("responsible", "responsible"),
            ("deputy", "deputy"),
            ("curator", "curator"),
        ):
            holder = zone.get(key)
            if not isinstance(holder, Mapping) or not holder.get("is_active", True):
                continue
            valid_to = zone.get("valid_to")
            out.setdefault(str(holder["id"]), []).append(
                CapabilityZone(
                    id=str(zone["id"]),
                    code=str(zone["code"]),
                    name=ZoneText.model_validate(zone["name"]),
                    role=role,
                    valid_to=str(valid_to) if valid_to else None,
                )
            )
    return out


def authorities_by_person(
    items: Iterable[SigningAuthority],
) -> dict[str, list[CapabilityAuthority]]:
    """Действующие права подписи EDS -> по держателю (`status` active или expiring)."""
    out: dict[str, list[CapabilityAuthority]] = {}
    for item in items:
        if item.status not in ("active", "expiring"):
            continue
        out.setdefault(item.holder.id, []).append(
            CapabilityAuthority(
                id=str(item.id),
                kinds=list(item.kinds),
                limit=item.limit,
                basis=item.basis,
                basis_number=item.basis_number,
                valid_to=item.valid_to.isoformat() if item.valid_to else None,
            )
        )
    return out
