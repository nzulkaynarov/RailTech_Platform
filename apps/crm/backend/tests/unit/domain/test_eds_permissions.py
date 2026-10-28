"""Права EDS сотрудника из ролей Платформы (волна 12, E4; ADR-0012 п. 5, sso-token.md).

Отображение «раздел × уровень → коды EDS» выписано вручную, независимо от `platform-rbac.yaml`:
ловит случайную правку каталога. Права вычисляются так же, как права ERP: несколько ролей —
объединение, уровень раздела — максимум, `full` включает `read`; неактивный — пусто.
"""

import json
from pathlib import Path

import pytest
import yaml

from app.domain import platform_roles_generated as generated
from app.domain.eds_permissions import EDS_PERMISSIONS
from app.domain.platform_roles import (
    RoleGrant,
    eds_permissions_for,
    eds_permissions_of,
)
from tests.platform_role_data import make_grant

REPO = Path(__file__).resolve().parents[6]
CONTRACTS = REPO / "packages" / "contracts"

# (раздел, уровень) -> коды EDS. Раздел без записи на уровне не даёт ничего.
EXPECTED: dict[tuple[str, str], set[str]] = {
    ("eds.inbox", "read"): {"letters.read", "registry.read"},
    ("eds.inbox", "full"): {"letters.read", "registry.read", "letters.register", "letters.resolve"},
    ("eds.drafts", "read"): set(),
    ("eds.drafts", "full"): {"approvals.decide"},
    ("eds.projects", "read"): {"registry.read"},
    ("eds.projects", "full"): {"registry.read", "registry.export"},
    ("eds.payments", "read"): {"registry.read"},
    ("eds.payments", "full"): {"registry.read", "payments.confirm"},
    ("eds.memo.create", "read"): set(),
    ("eds.memo.create", "full"): {"memos.create"},
    ("eds.memo.approve", "read"): set(),
    ("eds.memo.approve", "full"): {"memos.approve"},
}
ACCOUNTANT = {
    "letters.read",
    "registry.read",
    "registry.export",
    "payments.confirm",
    "memos.create",
}
#: Журнал шины EDS (W13-A2): только раздел `admin` уровня `full`.
BUS = "bus.manage"
#: Свой файл в EDS (письмо директору к «Создать заявку», D1-2b): раздел `crm.clients` уровня `full`.
UPLOAD = "files.upload"
ROLE_EDS: dict[str, set[str]] = {
    "ADMIN": {"memos.create", BUS},
    # D2-4: «Счета и оплаты» у директора — read: оплату подтверждает бухгалтер
    "DIRECTOR": set(EDS_PERMISSIONS) - {BUS, "payments.confirm"},
    "MANAGER": {"letters.read", "registry.read", "memos.create", UPLOAD},
    "SUPPLY": {"registry.read", "memos.create"},
    "ENGINEER": {"registry.read", "memos.create"},
    "ACCOUNTANT": ACCOUNTANT,
}


def test_snapshot_equals_the_eds_contract_and_the_catalog_schema() -> None:
    spec = yaml.safe_load((CONTRACTS / "openapi" / "eds.yaml").read_text(encoding="utf-8"))
    assert list(EDS_PERMISSIONS) == spec["components"]["schemas"]["EdsPermission"]["enum"]
    schema = json.loads((CONTRACTS / "platform-rbac.schema.json").read_text(encoding="utf-8"))
    assert set(schema["$defs"]["edsPermission"]["enum"]) == set(EDS_PERMISSIONS)


def test_every_code_in_the_catalog_is_an_eds_code() -> None:
    used = {p for table in generated.EDS_BACKEND.values() for ps in table.values() for p in ps}
    assert used <= set(EDS_PERMISSIONS)
    assert used == set(EDS_PERMISSIONS), "каждый код v1 кому-то выдаётся"


def test_expectation_table_covers_every_eds_element() -> None:
    elements = {
        (k, lv)
        for k in generated.RESOURCE_KEYS
        if k.startswith("eds.")
        for lv in generated.RESOURCE_LEVELS[k]
    }
    assert set(EXPECTED) == elements


@pytest.mark.parametrize(("element", "codes"), list(EXPECTED.items()), ids=lambda v: str(v))
def test_every_catalog_element_gives_the_expected_eds_codes(
    element: tuple[str, str], codes: set[str]
) -> None:
    resource, level = element
    assert set(eds_permissions_for({resource: level})) == codes
    assert set(eds_permissions_of([RoleGrant({resource: level})])) == codes


def test_sections_of_crm_and_erp_give_no_eds_codes_except_the_bus_journal() -> None:
    keys = generated.RESOURCE_KEYS
    other = {
        k: "full" for k in keys if not k.startswith("eds.") and k not in ("admin", "crm.clients")
    }
    assert eds_permissions_for(other) == ()
    # D1-2b: «Клиенты» полный — только свой файл (письмо директору), ни писем, ни документов
    assert eds_permissions_for({"crm.clients": "full"}) == (UPLOAD,)
    assert eds_permissions_for({"crm.clients": "read"}) == ()
    assert eds_permissions_for({"admin": "full"}) == (BUS,)
    assert eds_permissions_for({"admin": "read"}) == ()


@pytest.mark.parametrize("legacy", list(ROLE_EDS))
def test_every_system_role_and_template_gives_the_expected_eds_codes(legacy: str) -> None:
    codes = eds_permissions_of([make_grant(legacy)])
    assert set(codes) == ROLE_EDS[legacy]
    assert list(codes) == sorted(codes), "список сортирован"


def test_director_exports_the_registry_but_does_not_confirm_payments() -> None:
    """D2-4 (Q-D2-4-1 п. 1): директор читает счета и выгружает реестр, оплату ведёт бухгалтер."""
    codes = set(eds_permissions_of([make_grant("DIRECTOR")]))
    assert codes == set(EDS_PERMISSIONS) - {BUS, "payments.confirm"}
    assert {"registry.read", "registry.export"} <= codes
    # бухгалтер сохраняет всё, что имел
    assert set(eds_permissions_of([make_grant("ACCOUNTANT")])) == ACCOUNTANT
    assert eds_permissions_of([make_grant("ADMIN")]) == (BUS, "memos.create")


def test_manager_and_accountant_is_the_union_including_payment_confirmation() -> None:
    codes = eds_permissions_of([make_grant("MANAGER"), make_grant("ACCOUNTANT")])
    assert set(codes) == ACCOUNTANT | {UPLOAD}
    assert "payments.confirm" in codes
    assert "payments.confirm" not in eds_permissions_of([make_grant("MANAGER")])


def test_union_takes_the_maximum_level_and_is_independent_of_order() -> None:
    read = RoleGrant({"eds.payments": "read", "eds.inbox": "full"})
    full = RoleGrant({"eds.payments": "full", "eds.inbox": "read"})
    expected = {
        "letters.read",
        "registry.read",
        "letters.register",
        "letters.resolve",
        "payments.confirm",
    }
    assert set(eds_permissions_of([read, full])) == expected
    assert eds_permissions_of([read, full]) == eds_permissions_of([full, read])


def test_inactive_employee_and_employee_without_roles_have_no_eds_codes() -> None:
    director = [make_grant("DIRECTOR")]
    assert eds_permissions_of(director, is_active=False) == ()
    assert eds_permissions_of([]) == ()
    assert eds_permissions_of([RoleGrant({})]) == ()
