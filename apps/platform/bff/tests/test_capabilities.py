"""«Что может человек» (ДОСТ-1): расчёт строк каталога и охранный тест правдивости.

Правило: экран не называет возможностью то, что бэкенд откажет, и не прячет то, что он разрешает.
Здесь оно проверяется так: (1) коды бэкендов по ролям пересчитываются независимо — прямо из
`platform-rbac.yaml` и эталона матриц, мимо сгенерированных таблиц; (2) каждый код каталога прав
назван каким-то действием (ничего не спрятано); (3) условие BFF действия сверяется с настоящим
маршрутом BFF — 403 или нет — на выборке: `admin`, `eds.projects`, `eds.payments`, `erp.stock`,
`crm.clients`, `eds.signing.manage`. Сверка кодов с самими бэкендами —
`packages/contracts/tests/test_platform_capabilities.py` и
`apps/crm/backend/tests/unit/domain/test_capabilities_truth.py`.
"""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.capabilities import (
    CAPABILITIES,
    ERP_ALL,
    action_on,
    evaluate,
    held_by,
    summarize,
)
from app.capability_views import Extras, Person, RoleView, card, matrix, prepare, warnings
from app.rbac import allows
from tests.backends import Backends
from tests.conftest import Web
from tests.rbac_oracle import FIELDS, ROLES, access_of
from tests.roles import ref

RBAC = yaml.safe_load(
    (Path(__file__).resolve().parents[4] / "packages/contracts/platform-rbac.yaml").read_text(
        encoding="utf-8"
    )
)
RANK = {"read": 1, "full": 2}


def view(code: str) -> RoleView:
    r = ref(code)
    return RoleView(r["id"], r["name"], r["system"], r["code"], r["access"], r["restricted_fields"])


def level_of(roles: list[str], key: str) -> str:
    return evaluate(held_by([view(c) for c in roles]))[key].level


# --- (1) независимый пересчёт кодов -----------------------------------------------------------


def oracle_codes(roles: list[str]) -> dict[str, set[str]]:
    """Коды бэкендов по ролям прямо из platform-rbac.yaml и эталона матриц: без generated-таблиц."""
    access: dict[str, str] = {}
    fields: set[str] = set()
    for code in roles:
        for resource, level in access_of(code).items():
            if RANK[level] > RANK.get(access.get(resource) or "", 0):
                access[resource] = level
        fields |= set(FIELDS[code])
    codes: dict[str, set[str]] = {"crm": set(), "erp": set(), "eds": set()}
    for resource in RBAC["resources"]:
        held_level = access.get(resource["key"])
        if held_level is None:
            continue
        for backend, by_level in (resource.get("backend") or {}).items():
            for lv, listed in by_level.items():
                if RANK[lv] <= RANK[held_level]:
                    codes[backend].update(listed)
    for name in fields:
        codes["erp"].update(RBAC["restricted_fields"][name]["backend"].get("erp", []))
    if "ADMIN" in roles:
        codes["erp"].update(ERP_ALL)  # суперпользователь ERP (аудит К1)
    return codes


COMBOS = [[c] for c in ROLES] + [
    ["MANAGER", "ACCOUNTANT"],
    ["SUPPLY", "ENGINEER"],
    ["DIRECTOR", "ADMIN"],
]


@pytest.mark.parametrize("roles", COMBOS, ids="+".join)
def test_codes_match_an_independent_recount_from_the_contract(roles: list[str]) -> None:
    held = held_by([view(c) for c in roles])
    expected = oracle_codes(roles)
    assert {b: set(c) for b, c in held.codes.items()} == expected


# --- каталог ----------------------------------------------------------------------------------


def test_catalog_is_about_thirty_capabilities_and_every_action_has_a_known_condition() -> None:
    assert 28 <= len(CAPABILITIES) <= 36
    sections = {r["key"] for r in RBAC["resources"]}
    for cap in CAPABILITIES:
        for level in cap["levels"]:
            for action in level["actions"]:
                for gate in action["gates"]:
                    for alternative in gate.split("|"):
                        assert alternative.split(":")[0] in sections, (cap["key"], alternative)


def test_every_code_the_roles_can_grant_is_named_by_some_action() -> None:
    """Скрыть то, что бэкенд разрешает, нельзя: каждый код каталога прав — в каком-то действии."""
    named: dict[str, set[str]] = {"crm": set(), "erp": set(), "eds": set()}
    for cap in CAPABILITIES:
        for level in cap["levels"]:
            for action in level["actions"]:
                for backend in named:
                    named[backend].update(action.get(backend, ()))
    granted: dict[str, set[str]] = {"crm": set(), "erp": set(), "eds": set()}
    for resource in RBAC["resources"]:
        for backend, by_level in (resource.get("backend") or {}).items():
            for listed in by_level.values():
                granted[backend].update(listed)
    for field in RBAC["restricted_fields"].values():
        for backend, listed in field["backend"].items():
            granted[backend].update(listed)
    assert {b: sorted(granted[b] - named[b]) for b in granted} == {"crm": [], "erp": [], "eds": []}


# --- строки у типовых ролей -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("roles", "key", "level"),
    [
        (["MANAGER"], "leads", "work"),
        (["MANAGER"], "contract", "view"),
        (["MANAGER"], "payments", "view"),
        (["MANAGER"], "staff", "none"),
        (["ACCOUNTANT"], "payments", "decide"),
        (["ACCOUNTANT"], "contract", "decide"),
        (["ACCOUNTANT"], "leads", "none"),
        (["LAWYER"], "contract_templates", "decide"),
        (["REGISTRAR"], "lead_triage", "work"),
        (["REGISTRAR"], "leads", "view"),
        (["DIRECTOR"], "quote", "decide"),
        (["DIRECTOR"], "exceptional", "none"),
        (["DIRECTOR"], "staff", "view"),
        (["ADMIN"], "exceptional", "decide"),
        (["ADMIN"], "staff", "work"),
        (["ADMIN"], "signing_registry", "work"),
        (["ADMIN"], "leads", "none"),
        (["DIRECTOR", "ADMIN"], "staff", "work"),
        (["SUPPLY"], "cost_margin", "view"),
        (["MANAGER"], "cost_margin", "none"),
    ],
)
def test_levels_of_template_roles(roles: list[str], key: str, level: str) -> None:
    assert level_of(roles, key) == level


def test_partial_means_an_action_of_this_or_a_lower_level_is_off() -> None:
    lawyer = evaluate(held_by([view("LAWYER")]))["contract"]
    assert lawyer.level == "decide"
    assert lawyer.partial  # визы финансов нет и подготовки договора нет
    assert lawyer.on["visa_legal"]
    assert not lawyer.on["visa_finance"]
    manager_all = evaluate(held_by([view("MANAGER_ALL")]))["calc"]
    assert manager_all.level == "decide"
    assert not manager_all.partial


def test_cost_margin_follows_the_field_not_the_section() -> None:
    """Тот, у кого поле `cost_margin` скрыто, не «видит себестоимость», даже с полным расчётом."""
    assert level_of(["MANAGER"], "calc") == "work"
    assert level_of(["MANAGER"], "cost_margin") == "none"
    assert level_of(["DIRECTOR"], "cost_margin") == "view"


def test_erp_superuser_is_shown_as_what_erp_really_allows() -> None:
    held = held_by([view("ADMIN")])
    assert held.codes["erp"] == ERP_ALL
    # Платформа администратору лидов и расчёта не открывает: строка «нет», хотя ERP разрешает всё.
    assert level_of(["ADMIN"], "calc") == "none"


def test_a_custom_role_with_full_settings_is_not_the_exceptional_actions() -> None:
    custom = RoleView(99, "Своя", False, None, {"admin": "full", "company.settings": "full"}, [])
    assert evaluate(held_by([custom]))["exceptional"].level == "none"


def test_summary_is_words_from_the_catalog_and_deterministic() -> None:
    states = evaluate(held_by([view("ACCOUNTANT")]))
    first, second = summarize(states), summarize(states)
    assert first == second
    assert first.does
    assert first.decides
    assert first.lacks
    assert "счета" in first.does["ru"]
    assert "подтверждать оплату" in first.decides["ru"]
    assert "лиды" in first.lacks["ru"]
    assert first.does["uz"]
    assert first.does["en"]


# --- предупреждения ---------------------------------------------------------------------------


def person(pid: str, roles: list[str], **extra: Any) -> Person:
    return Person(pid, f"Имя {pid}", "ИФ", None, None, [view(c) for c in roles], **extra)


def test_the_only_decider_without_a_deputy_is_warned() -> None:
    team = prepare(
        [person("1", ["DIRECTOR"]), person("2", ["MANAGER"]), person("3", ["ACCOUNTANT"])]
    )
    found = {
        (w.code, w.capability, w.person.id if w.person else None)
        for w in warnings(team, Extras(), date(2026, 11, 27))
    }
    assert ("only_decider", "quote", "1") in found
    assert ("only_decider", "payments", "3") in found
    assert not [f for f in found if f[0] == "only_decider" and f[1] == "exceptional"]
    only = [w for w in warnings(team, Extras(), date(2026, 11, 27)) if w.capability == "quote"]
    assert only[0].has_deputy is False


def test_nobody_decides_when_no_one_holds_the_level() -> None:
    team = prepare([person("2", ["MANAGER"])])
    found = {(w.code, w.capability) for w in warnings(team, Extras(), date(2026, 11, 27))}
    assert ("nobody_decides", "quote") in found


def test_visa_without_signing_only_when_the_register_could_be_read() -> None:
    team = prepare([person("3", ["ACCOUNTANT"])])
    unknown = warnings(team, Extras(signing_known=False), date(2026, 11, 27))
    assert not [w for w in unknown if w.code == "visa_without_signing"]
    known = warnings(team, Extras(signing_known=True), date(2026, 11, 27))
    assert [
        w for w in known if w.code == "visa_without_signing" and w.person and w.person.id == "3"
    ]


def test_card_lists_who_else_can_and_the_matrix_has_every_capability() -> None:
    team = prepare(
        [person("1", ["MANAGER"]), person("2", ["MANAGER_ALL"]), person("3", ["SUPPLY"])]
    )
    result = card(team[0], team, Extras(), date(2026, 11, 27))
    rows = {r.key: r for g in result.groups for r in g.rows}
    assert [p.id for p in rows["leads"].others] == ["2"]
    assert rows["leads"].from_roles
    assert rows["leads"].from_roles[0].name == "Менеджер"
    table = matrix(team, Extras(), date(2026, 11, 27))
    assert set(table.employees[0].cells) == {c["key"] for c in CAPABILITIES}


# --- (2) сверка с настоящими маршрутами BFF ---------------------------------------------------

PROBES = [
    ("/api/v1/admin/users", "staff", "read"),
    ("/api/v1/eds/projects", "contract", "read"),
    ("/api/v1/eds/payments", "invoices", "read"),
    ("/api/v1/erp/stock/balances", "warehouse", "read"),
    ("/api/v1/crm/clients", "clients", "read"),
    ("/api/v1/eds/signing/authorities", "signing_registry", "keep"),
]
BFF_ROLES = ["ADMIN", "DIRECTOR", "MANAGER", "SUPPLY", "ACCOUNTANT", "REGISTRAR", "LAWYER"]


def _action(cap_key: str, action_key: str) -> dict[str, Any]:
    cap = next(c for c in CAPABILITIES if c["key"] == cap_key)
    return next(a for lv in cap["levels"] for a in lv["actions"] if a["key"] == action_key)


@pytest.mark.parametrize("role", BFF_ROLES)
async def test_bff_gates_agree_with_the_real_routes(web: Web, be: Backends, role: str) -> None:
    """Условие BFF действия выполнено ⇔ маршрут не отвечает 403 (бэкенды не подняты)."""
    await web.login([role])
    held = held_by([view(role)])
    for url, cap, key in PROBES:
        action = _action(cap, key)
        gates_ok = all(
            any(allows(held.access, g.split(":")[0], g.split(":")[1]) for g in gate.split("|"))
            for gate in action["gates"]
        )
        response = await web.client.get(url)
        assert (response.status_code != 403) == gates_ok, (role, url, response.status_code)
        # и расчёт строки не противоречит маршруту по условию BFF
        if not gates_ok:
            assert not action_on(action, held), (role, cap, key)
