"""RBAC по ролям-данным (ADR-0012): ячейки каталога, объединение ролей, вид, меню, очередь, поля.

Роли приходят из CRM с матрицами; эталон шести предустановок — `rbac_oracle` (каталог версии 2
дословно). Коды ролей в логике BFF не встречаются: проверки — по разделам матриц.
"""

import itertools
from pathlib import Path
from typing import Annotated, Any

import pytest
import yaml
from fastapi import Depends

from app import rbac
from app.deps import Authed, require
from app.rbac_generated import MENU, MODULES, QUEUE, RESOURCE_MODULE
from app.session import SessionRole
from tests.conftest import Web
from tests.rbac_oracle import FIELDS, MATRIX, MODULE_OF, RANK, ROLES, access_of, level, union
from tests.roles import custom, ref

CONTRACT = Path(__file__).resolve().parents[4] / "packages/contracts/platform-rbac.yaml"
CELLS = list(itertools.product(ROLES, MATRIX))


def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return loaded


def role(code_or_ref: str | dict[str, Any]) -> SessionRole:
    return SessionRole.model_validate(ref(code_or_ref))


def roles(*codes: str | dict[str, Any]) -> list[SessionRole]:
    return [role(c) for c in codes]


def test_catalog_has_eighteen_sections_in_oracle_order() -> None:
    assert list(RESOURCE_MODULE) == list(MATRIX)
    assert len(CELLS) == 108
    assert {k: RESOURCE_MODULE[k] for k in MATRIX} == MODULE_OF


def test_contract_equals_oracle() -> None:
    """Системные роли и шаблоны каталога — эталон версии 2 (матрица и поля)."""
    data = spec()
    catalog = {**data["system_roles"], **data["templates"]}
    assert list(catalog) == ["ADMIN", "DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"]
    for code, body in catalog.items():
        assert body["access"] == access_of(code), code
        assert sorted(body["restricted_fields"]) == sorted(FIELDS[code]), code
    assert [r["key"] for r in data["resources"]] == list(MATRIX)


@pytest.mark.parametrize(("code", "key"), CELLS)
def test_cell_level_and_allows(code: str, key: str) -> None:
    """Каждая ячейка: уровень раздела у роли и проверка `allows` на чтение и изменение."""
    expected = level(code, key)
    access = rbac.merge([role(code)])

    assert (rbac.level_for(access, key) or "hidden") == expected
    assert rbac.allows(access, key, "read") is (RANK[expected] >= 1)
    assert rbac.allows(access, key, "full") is (RANK[expected] == 2)
    assert (key in access) is (expected != "hidden")


@pytest.fixture
def probes(web: Web) -> None:
    """Маршруты-пробы: на каждый раздел и уровень свой `require`."""
    for key in MATRIX:
        for need in ("read", "full"):

            def make(k: str = key, n: str = need) -> None:
                @web.app.get(f"/api/v1/_rbac/{n}/{k}")
                async def probe(_: Annotated[Authed, Depends(require(k, n))]) -> dict[str, bool]:
                    return {"ok": True}

            make()


@pytest.mark.parametrize("code", ROLES)
async def test_every_cell_through_http(web: Web, probes: None, code: str) -> None:
    """`require(resource, level)` на живом маршруте: 200 или 403 в каждой из 18 x 2 ячеек."""
    assert (await web.login([code])).status_code == 200

    for key in MATRIX:
        for need in ("read", "full"):
            response = await web.client.get(f"/api/v1/_rbac/{need}/{key}")
            allowed = RANK[level(code, key)] >= RANK[need]
            assert response.status_code == (200 if allowed else 403), (code, key, need)
            if not allowed:
                body = response.json()
                assert body["code"] == "FORBIDDEN"
                assert body["source"] == "bff"
                assert body["details"] == {"resource": key, "need": need}


MIXED = custom(
    40, "Менеджер и бухгалтер", {"crm.leads": "full", "eds.payments": "full"}, ("totals_only",)
)


async def test_created_role_opens_exactly_its_sections_through_http(web: Web, probes: None) -> None:
    """Роль без кода, созданная администратором: доступ — ровно её разделы (ADR-0012)."""
    assert (await web.login([MIXED])).status_code == 200

    for key in MATRIX:
        for need in ("read", "full"):
            response = await web.client.get(f"/api/v1/_rbac/{need}/{key}")
            allowed = key in ("crm.leads", "eds.payments")
            assert response.status_code == (200 if allowed else 403), (key, need)


# --- права = объединение ролей --------------------------------------------------------------------


@pytest.mark.parametrize(("a", "b"), list(itertools.combinations(ROLES, 2)))
def test_rights_are_the_union_of_roles(a: str, b: str) -> None:
    """Права = объединение ролей: максимум по разделу, порядок ролей не важен."""
    for key in MATRIX:
        expected = union([a, b], key)
        assert (rbac.level_for(rbac.merge(roles(a, b)), key) or "hidden") == expected
        assert (rbac.level_for(rbac.merge(roles(b, a)), key) or "hidden") == expected


def test_union_of_created_roles_takes_the_maximum_and_all_fields() -> None:
    first = custom(41, "Продажи", {"crm.leads": "read", "eds.payments": "full"}, ("totals_only",))
    second = custom(42, "Лиды", {"crm.leads": "full", "eds.inbox": "read"}, ("cost_margin",))

    merged = rbac.merge(roles(first, second))

    assert merged == {"crm.leads": "full", "eds.inbox": "read", "eds.payments": "full"}
    assert list(merged) == ["crm.leads", "eds.inbox", "eds.payments"]  # порядок каталога
    assert rbac.fields_of(roles(first, second)) == ["cost_margin", "totals_only"]


def test_unknown_sections_and_levels_of_a_role_give_nothing() -> None:
    odd = custom(43, "Странная", {"payroll": "full", "admin": "owner", "erp.calc.goods": "read"})

    assert rbac.merge(roles(odd)) == {}  # чужой раздел, чужой уровень, read там, где только full
    assert rbac.merge([]) == {}


def test_unknown_resource_is_an_error() -> None:
    with pytest.raises(KeyError):
        rbac.level_for({}, "payroll")
    with pytest.raises(KeyError):
        require("payroll")


# --- активная роль — вид -------------------------------------------------------------------------


def test_active_role_is_the_view_and_does_not_change_rights() -> None:
    """Активная роль сужает вид (модули, разделы, поля, очередь), права — по объединению."""
    owned = roles("SUPPLY", MIXED)

    view = rbac.View.of(rbac.view_roles(owned, 40))
    union_access = rbac.merge(owned)

    assert view.access == {"crm.leads": "full", "eds.payments": "full"}
    assert rbac.modules_for(view.access) == ["crm", "eds"]
    assert view.fields == ("totals_only",)
    assert "calc_task" not in view.kinds
    assert "answer_lead" in view.kinds
    assert rbac.allows(union_access, "erp.calc", "full")  # право снабженца осталось
    assert rbac.View.of(rbac.view_roles(owned, None)).access == union_access
    assert rbac.view_roles(owned, 999) == owned  # чужая роль не даёт вид


def test_queue_item_belongs_to_the_first_view_role_that_gives_the_kind() -> None:
    view = rbac.View.of(roles("SUPPLY", MIXED, "MANAGER"))

    assert view.role_for("answer_lead") == 40
    assert view.role_for("calc_task") == 4
    assert view.role_for("approve_quote") is None


# --- модули, меню, очередь -----------------------------------------------------------------------


@pytest.mark.parametrize("code", ROLES)
def test_modules_follow_visible_sections(code: str) -> None:
    expected = [
        m for m in MODULES if any(level(code, k) != "hidden" for k in MATRIX if MODULE_OF[k] == m)
    ]

    assert rbac.modules_for(rbac.merge(roles(code))) == expected
    assert "dashboard" in expected  # «Моя очередь» видна всем предустановкам
    assert ("admin" in expected) is (code in {"DIRECTOR", "ADMIN"})


@pytest.mark.parametrize("code", ROLES)
def test_menu_item_visible_if_any_section_is_visible(code: str) -> None:
    access = rbac.merge(roles(code))
    menu = rbac.menu_for(access)

    for module, items in MENU.items():
        for item, sections in items.items():
            expected = any(level(code, s) != "hidden" for s in sections)
            assert (item in menu[module]) is expected, (code, module, item)
        assert menu[module] == [i for i in items if i in menu[module]]
    assert [m for m in MODULES if menu[m]] == rbac.modules_for(access)


def test_menu_sections_exist_and_cover_every_section() -> None:
    covered = {s for items in MENU.values() for sections in items.values() for s in sections}
    # Визы расчёта — возможности внутри экрана «Расчёт», своего пункта меню у них нет.
    assert set(MATRIX) - covered == {"erp.calc.goods", "erp.calc.services"}
    for module, items in MENU.items():
        for sections in items.values():
            assert all(RESOURCE_MODULE[s] in MODULES for s in sections)
        assert module in MODULES


def test_menu_examples() -> None:
    admin = rbac.merge(roles("ADMIN"))
    assert rbac.menu_for(admin)["dashboard"] == ["queue"]
    assert rbac.menu_for(admin)["admin"] == [
        "roles",
        "org",
        "integrations",
        "bus",
        "tickets",
        "company",
        "audit",
    ]
    assert "summary" in rbac.menu_for(rbac.merge(roles("ACCOUNTANT")))["dashboard"]
    assert "summary" not in rbac.menu_for(rbac.merge(roles("MANAGER", "SUPPLY")))["dashboard"]
    assert rbac.menu_for(rbac.merge(roles("SUPPLY")))["chats"] == ["all", "internal", "contacts"]
    mixed = rbac.menu_for(rbac.merge(roles(MIXED)))
    assert mixed["crm"] == ["messages", "leads", "channels", "kb"]
    assert mixed["eds"] == ["documents", "payments"]
    assert mixed["dashboard"] == []


def test_queue_kinds_follow_the_catalog_queue_section() -> None:
    for code in ROLES:
        access = rbac.merge(roles(code))
        expected = [
            kind
            for kind, (resource, need) in QUEUE.items()
            if RANK[level(code, resource)] >= RANK[need]
        ]
        assert rbac.queue_kinds(access) == expected, code
    assert rbac.queue_kinds(rbac.merge(roles(MIXED))) == [
        "answer_lead",
        "take_lead",
        "confirm_payment",
        "issue_invoice",
        "pay_memo",
        "overdue_invoice",
    ]


def test_backends_of_the_sections() -> None:
    only_payments = rbac.merge(roles(custom(44, "Касса", {"eds.payments": "full"})))
    assert not rbac.gives_backend(only_payments, "crm")
    assert rbac.gives_backend(only_payments, "erp")
    assert rbac.gives_backend(rbac.merge(roles(MIXED)), "crm")


# --- поля с ограничением --------------------------------------------------------------------------


@pytest.mark.parametrize("code", ROLES)
def test_restricted_fields_per_role(code: str) -> None:
    expected = [f for f in ("cost_margin", "supplier_prices", "totals_only") if f in FIELDS[code]]

    assert rbac.fields_of(roles(code)) == expected


RULES = {"cost_margin": ("cost", "margin"), "supplier_prices": ("supplier_price",)}
PAYLOAD: dict[str, Any] = {
    "number": "КП-2026-014",
    "total": 1200,
    "lines": [
        {"name": "Рельс", "cost": 700, "margin": 500, "supplier_price": 650},
        {"name": "Крепёж", "cost": 40, "margin": 10, "supplier_price": 35},
    ],
    "summary": {"margin": 510, "nested": [{"cost": 1}]},
}


def test_strip_removes_fields_nobody_of_the_roles_sees() -> None:
    result = rbac.strip_restricted(PAYLOAD, rbac.fields_of(roles("MANAGER")), RULES)

    assert result == {
        "number": "КП-2026-014",
        "total": 1200,
        "lines": [{"name": "Рельс"}, {"name": "Крепёж"}],
        "summary": {"nested": [{}]},
    }
    assert "cost" in PAYLOAD["lines"][0]  # исходный ответ не изменён


def test_strip_keeps_fields_visible_to_any_role() -> None:
    accountant = rbac.strip_restricted(PAYLOAD, rbac.fields_of(roles("ACCOUNTANT")), RULES)
    assert accountant["lines"][0] == {"name": "Рельс", "supplier_price": 650}
    assert rbac.strip_restricted(PAYLOAD, rbac.fields_of(roles("DIRECTOR")), RULES) == PAYLOAD
    both = rbac.strip_restricted(PAYLOAD, rbac.fields_of(roles("MANAGER", "SUPPLY")), RULES)
    assert both == PAYLOAD


def test_strip_rejects_unknown_group() -> None:
    with pytest.raises(ValueError, match="payroll"):
        rbac.strip_restricted(PAYLOAD, [], {"payroll": ("salary",)})
