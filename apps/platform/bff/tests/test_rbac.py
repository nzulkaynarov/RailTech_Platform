"""RBAC: тест на каждую ячейку матрицы (6 ролей x 15 разделов), объединение ролей, меню, поля."""

import itertools
from pathlib import Path
from typing import Annotated, Any

import pytest
import yaml
from fastapi import Depends

from app import rbac
from app.deps import Authed, require
from app.rbac_generated import ACCESS, MENU, MODULES, RESOURCE_MODULE, ROLES
from tests.conftest import Web
from tests.rbac_oracle import MATRIX, RANK, RESTRICTED, level, union
from tests.rbac_oracle import ROLES as ORACLE_ROLES

CONTRACT = Path(__file__).resolve().parents[4] / "packages/contracts/platform-rbac.yaml"
CELLS = list(itertools.product(ORACLE_ROLES, MATRIX))


def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return loaded


def test_matrix_has_six_roles_and_fifteen_sections() -> None:
    assert tuple(ROLES) == ORACLE_ROLES
    assert len(MATRIX) == 15
    assert len(CELLS) == 90
    assert list(ACCESS) == list(MATRIX)  # порядок строк — SPEC-v3 §4.2 дословно


def test_contract_equals_spec_oracle() -> None:
    rows = {r["key"]: r["access"] for r in spec()["resources"]}
    assert list(rows) == list(MATRIX)
    for key, access in rows.items():
        assert [access[role] for role in ORACLE_ROLES] == [level(r, key) for r in ORACLE_ROLES]
    restricted = {k: tuple(v["visible_to"]) for k, v in spec()["restricted_fields"].items()}
    assert restricted == RESTRICTED


@pytest.mark.parametrize(("role", "key"), CELLS)
def test_cell_level_and_allows(role: str, key: str) -> None:
    expected = level(role, key)

    assert rbac.level_for([role], key) == expected
    assert ACCESS[key][role] == expected  # type: ignore[index]
    assert rbac.allows([role], key, "read") is (RANK[expected] >= 1)
    assert rbac.allows([role], key, "full") is (RANK[expected] == 2)
    visible = rbac.resources_for([role])
    assert (key in visible) is (expected != "hidden")
    if expected != "hidden":
        assert visible[key] == expected


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


@pytest.mark.parametrize("role", ORACLE_ROLES)
async def test_every_cell_through_http(web: Web, probes: None, role: str) -> None:
    """`require(resource, level)` на живом маршруте: 200 или 403 в каждой из 15 x 2 ячеек."""
    assert (await web.login([role])).status_code == 200

    for key in MATRIX:
        for need in ("read", "full"):
            response = await web.client.get(f"/api/v1/_rbac/{need}/{key}")
            allowed = RANK[level(role, key)] >= RANK[need]
            assert response.status_code == (200 if allowed else 403), (role, key, need)
            if not allowed:
                body = response.json()
                assert body["code"] == "FORBIDDEN"
                assert body["source"] == "bff"
                assert body["details"] == {"resource": key, "need": need}


@pytest.mark.parametrize(("a", "b"), list(itertools.combinations(ORACLE_ROLES, 2)))
def test_two_roles_take_the_maximum(a: str, b: str) -> None:
    for key in MATRIX:
        assert rbac.level_for([a, b], key) == union([a, b], key)
        assert rbac.level_for([b, a], key) == union([a, b], key)


def test_all_roles_and_empty_set() -> None:
    for key in MATRIX:
        assert rbac.level_for(list(ORACLE_ROLES), key) == union(list(ORACLE_ROLES), key)
        assert rbac.level_for([], key) == "hidden"
        assert rbac.level_for(["SUPERUSER"], key) == "hidden"  # чужой код роли ничего не даёт
    assert rbac.level_for(["SUPERUSER", "ADMIN"], "admin") == "full"


def test_unknown_resource_is_an_error() -> None:
    with pytest.raises(KeyError):
        rbac.level_for(["ADMIN"], "payroll")
    with pytest.raises(KeyError):
        require("payroll")


def test_known_roles_dedup_and_order() -> None:
    assert rbac.known_roles(["ADMIN", "MANAGER", "ADMIN", "X"]) == ["MANAGER", "ADMIN"]


def test_view_roles() -> None:
    owned = ["SUPPLY", "ACCOUNTANT"]
    assert rbac.view_roles(owned, None) == ["SUPPLY", "ACCOUNTANT"]
    assert rbac.view_roles(owned, "ACCOUNTANT") == ["ACCOUNTANT"]
    assert rbac.view_roles(owned, "ADMIN") == ["SUPPLY", "ACCOUNTANT"]  # чужая роль не даёт вид


# --- модули и меню --------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ORACLE_ROLES)
def test_modules_follow_visible_sections(role: str) -> None:
    expected = [
        m
        for m in MODULES
        if any(level(role, k) != "hidden" for k in MATRIX if k.split(".")[0] == m)
    ]

    assert rbac.modules_for([role]) == expected
    assert "dashboard" in expected  # «Моя очередь» видна всем
    assert ("admin" in expected) is (role in {"DIRECTOR", "ADMIN"})


@pytest.mark.parametrize("role", ORACLE_ROLES)
def test_menu_item_visible_if_any_section_is_not_hidden(role: str) -> None:
    menu = rbac.menu_for([role])

    for module, items in MENU.items():
        for item, sections in items.items():
            expected = any(level(role, s) != "hidden" for s in sections)
            assert (item in menu[module]) is expected, (role, module, item)
        # Порядок пунктов — как в контракте.
        assert menu[module] == [i for i in items if i in menu[module]]
    # Модуль виден тогда и только тогда, когда виден хотя бы один его пункт.
    assert [m for m in MODULES if menu[m]] == rbac.modules_for([role])


def test_menu_sections_exist_and_cover_every_section() -> None:
    covered = {s for items in MENU.values() for sections in items.values() for s in sections}
    assert covered == set(MATRIX)  # ни один раздел матрицы не остался без пункта меню
    for module, items in MENU.items():
        for sections in items.values():
            assert all(RESOURCE_MODULE[s] in MODULES for s in sections)
        assert module in MODULES


def test_menu_examples_from_spec() -> None:
    assert rbac.menu_for(["ADMIN"])["dashboard"] == ["queue"]
    assert rbac.menu_for(["ADMIN"])["admin"] == ["roles", "org", "integrations", "tickets"]
    assert rbac.menu_for(["MANAGER"])["eds"] == [
        "documents",
        "inbox",
        "outbox",
        "projects",
        "drafts",
        "approvals",
        "payments",
    ]
    assert "summary" in rbac.menu_for(["ACCOUNTANT"])["dashboard"]  # read открывает пункт
    assert "summary" not in rbac.menu_for(["MANAGER", "SUPPLY"])["dashboard"]
    # Смешанный реестр: Chats · Все чаты виден по любому из двух разделов.
    assert "all" in rbac.menu_for(["SUPPLY"])["chats"]
    assert rbac.menu_for(["SUPPLY"])["chats"] == ["all", "internal", "contacts"]


# --- поля с ограничением --------------------------------------------------------------------------


@pytest.mark.parametrize("role", ORACLE_ROLES)
def test_restricted_fields_per_role(role: str) -> None:
    expected = [name for name, roles in RESTRICTED.items() if role in roles]

    assert rbac.restricted_fields_for([role]) == expected


def test_restricted_fields_union() -> None:
    assert rbac.restricted_fields_for(["DIRECTOR", "ACCOUNTANT"]) == [
        "cost_margin",
        "totals_only",
        "supplier_prices",
    ]
    assert rbac.restricted_fields_for(["MANAGER", "ENGINEER", "ADMIN"]) == []


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
    result = rbac.strip_restricted(PAYLOAD, ["MANAGER"], RULES)

    assert result == {
        "number": "КП-2026-014",
        "total": 1200,
        "lines": [{"name": "Рельс"}, {"name": "Крепёж"}],
        "summary": {"nested": [{}]},
    }
    assert "cost" in PAYLOAD["lines"][0]  # исходный ответ не изменён


def test_strip_keeps_fields_visible_to_any_role() -> None:
    # Бухгалтер видит цены поставщиков, но не себестоимость и маржу.
    accountant = rbac.strip_restricted(PAYLOAD, ["ACCOUNTANT"], RULES)
    assert accountant["lines"][0] == {"name": "Рельс", "supplier_price": 650}
    # Директор видит всё; объединение ролей раскрывает поле.
    assert rbac.strip_restricted(PAYLOAD, ["DIRECTOR"], RULES) == PAYLOAD
    both = rbac.strip_restricted(PAYLOAD, ["MANAGER", "SUPPLY"], RULES)
    assert both == PAYLOAD


def test_strip_rejects_unknown_group() -> None:
    with pytest.raises(ValueError, match="payroll"):
        rbac.strip_restricted(PAYLOAD, ["ADMIN"], {"payroll": ("salary",)})
