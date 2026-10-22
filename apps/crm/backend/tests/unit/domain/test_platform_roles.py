"""Роли Платформы (CRM-01): сгенерированный модуль = контракт, карта, объединение, провижининг."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from app.domain import platform_roles_generated as generated
from app.domain.erp_permissions import ERP_PERMISSIONS
from app.domain.erp_roles import ERP_ROLE_CODES as ERP_CATALOG
from app.domain.platform_roles import (
    PLATFORM_ROLE_GRANTS,
    derive_access,
    erp_access_for,
    normalize_platform_roles,
    normalize_position,
    platform_grants,
)

REPO = Path(__file__).resolve().parents[6]
RBAC = REPO / "packages" / "contracts" / "platform-rbac.yaml"
SEAM = REPO / "packages" / "contracts" / "openapi" / "erp-integration.yaml"
GENERATOR = REPO / "apps" / "crm" / "scripts" / "gen_platform_roles.py"
GENERATED = REPO / "apps" / "crm" / "backend" / "app" / "domain" / "platform_roles_generated.py"


def _contract() -> dict[str, dict[str, Any]]:
    roles: dict[str, dict[str, Any]] = yaml.safe_load(RBAC.read_text(encoding="utf-8"))["roles"]
    return roles


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_platform_roles", GENERATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Таблица §4 apps/platform/docs/04-integration-map.md, записанная независимо от контракта:
# (базовая роль CRM, role_codes ERP, права ERP поверх шаблонов).
TABLE = {
    "MANAGER": ("manager", ("VIEWER",), ("deal.manage",)),
    "DIRECTOR": ("viewer", ("HEAD",), ()),
    "SUPPLY": ("viewer", ("CATALOG_SUPPLY", "FULFILLMENT"), ("quote.build", "quote.edit_pricing")),
    "ENGINEER": ("viewer", ("FULFILLMENT",), ("quote.build",)),
    "ACCOUNTANT": ("manager", ("FINANCE",), ("contract.manage", "fulfillment.act")),
    "ADMIN": ("admin", (), ()),
}


def test_generated_module_is_exactly_what_the_generator_renders_from_the_contract() -> None:
    """«Сгенерированное = контракт»: файл в репозитории совпадает с выводом генератора по YAML."""
    spec = yaml.safe_load(RBAC.read_text(encoding="utf-8"))
    assert GENERATED.read_text(encoding="utf-8") == _generator().render(spec)


def test_generated_values_equal_the_contract_role_by_role() -> None:
    roles = _contract()
    assert list(generated.PLATFORM_ROLE_CODES) == list(roles)
    for code, spec in roles.items():
        assert generated.CRM_BASE_ROLE[code] == spec["crm_base_role"]
        assert generated.ERP_ROLE_CODES[code] == tuple(spec["erp_role_codes"])
        assert generated.ERP_EXTRA_PERMISSIONS[code] == tuple(spec["erp_extra_permissions"])
    assert set(generated.CRM_BASE_ROLE) == set(generated.PLATFORM_ROLE_CODES)


def test_generator_check_mode_passes_on_a_fresh_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["gen_platform_roles.py", "--check"])
    assert _generator().main() == 0


def test_contract_table_matches_the_documented_integration_map() -> None:
    """Таблица ролей из 04-integration-map §4 = контракт (ловит расхождение карты и кода)."""
    got = {
        code: (
            generated.CRM_BASE_ROLE[code],
            generated.ERP_ROLE_CODES[code],
            generated.ERP_EXTRA_PERMISSIONS[code],
        )
        for code in generated.PLATFORM_ROLE_CODES
    }
    assert got == TABLE


def test_erp_codes_and_permissions_are_known_to_the_seam_contract() -> None:
    schemas = yaml.safe_load(SEAM.read_text(encoding="utf-8"))["components"]["schemas"]
    seam_roles = set(schemas["SystemRoleCode"]["enum"])
    seam_permissions = set(schemas["ErpPermission"]["enum"])
    assert seam_roles == set(ERP_CATALOG)
    for code in generated.PLATFORM_ROLE_CODES:
        assert set(generated.ERP_ROLE_CODES[code]) <= seam_roles
        assert set(generated.ERP_EXTRA_PERMISSIONS[code]) <= seam_permissions
        assert set(generated.ERP_EXTRA_PERMISSIONS[code]) <= set(ERP_PERMISSIONS)


def test_the_seam_has_a_permissions_field_that_carries_the_extras() -> None:
    """Права поверх шаблонов ролей ERP уходят в `permissions` провижининга — поле есть в шве."""
    schemas = yaml.safe_load(SEAM.read_text(encoding="utf-8"))["components"]["schemas"]
    request = schemas["ProvisionUserRequest"]
    assert "permissions" in request["required"]
    assert request["properties"]["permissions"]["items"] == {
        "$ref": "#/components/schemas/ErpPermission"
    }


@pytest.mark.parametrize(("code", "expected"), list(TABLE.items()))
def test_every_role_derives_crm_role_erp_roles_and_permissions(
    code: str, expected: tuple[str, tuple[str, ...], tuple[str, ...]]
) -> None:
    crm_role, role_codes, extra = expected
    derived = derive_access([code])
    assert derived.crm_role == crm_role
    assert derived.platform_access == ("crm", "erp")
    assert derived.erp_role_codes == role_codes
    assert derived.erp_extra_permissions == extra


@pytest.mark.parametrize(("code", "expected"), list(TABLE.items()))
def test_every_role_gives_the_erp_provisioning_role_and_rights(
    code: str, expected: tuple[str, tuple[str, ...], tuple[str, ...]]
) -> None:
    access = erp_access_for([code])
    if code == "ADMIN":
        assert (access.role, access.permissions) == ("admin", ERP_PERMISSIONS)
    else:
        assert (access.role, access.permissions) == ("backoffice", expected[2])


@pytest.mark.parametrize(
    ("codes", "crm_role", "role_codes", "extra"),
    [
        pytest.param(
            ["SUPPLY", "ENGINEER"],
            "viewer",
            ("FULFILLMENT", "CATALOG_SUPPLY"),
            ("quote.build", "quote.edit_pricing"),
            id="supply+engineer-dedupes",
        ),
        pytest.param(
            ["MANAGER", "DIRECTOR"],
            "manager",
            ("HEAD", "VIEWER"),
            ("deal.manage",),
            id="manager-outranks-viewer",
        ),
        pytest.param(
            ["DIRECTOR", "ACCOUNTANT"],
            "manager",
            ("FINANCE", "HEAD"),
            ("contract.manage", "fulfillment.act"),
            id="accountant+director",
        ),
        pytest.param(
            ["ADMIN", "MANAGER"],
            "admin",
            ("VIEWER",),
            ("deal.manage",),
            id="admin-outranks-all",
        ),
    ],
)
def test_union_of_two_roles(
    codes: list[str], crm_role: str, role_codes: tuple[str, ...], extra: tuple[str, ...]
) -> None:
    derived = derive_access(codes)
    assert derived.crm_role == crm_role
    # Порядок — как в каталогах ERP, а не в порядке ролей.
    assert sorted(derived.erp_role_codes) == sorted(role_codes)
    assert [c for c in ERP_CATALOG if c in derived.erp_role_codes] == list(derived.erp_role_codes)
    assert sorted(derived.erp_extra_permissions) == sorted(extra)
    assert [p for p in ERP_PERMISSIONS if p in extra] == list(derived.erp_extra_permissions)


def test_admin_with_other_roles_is_still_the_erp_superuser() -> None:
    access = erp_access_for(["ADMIN", "DIRECTOR"])
    assert (access.role, access.permissions) == ("admin", ERP_PERMISSIONS)


def test_derive_is_independent_of_order_and_duplicates() -> None:
    assert derive_access(["ENGINEER", "SUPPLY", "ENGINEER"]) == derive_access(
        ["SUPPLY", "ENGINEER"]
    )


def test_empty_set_has_no_derived_access() -> None:
    with pytest.raises(ValueError, match="empty"):
        derive_access([])


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ([], []),
        (["ADMIN", "MANAGER"], ["MANAGER", "ADMIN"]),  # порядок контракта
        (["SUPPLY", "SUPPLY"], ["SUPPLY"]),
    ],
)
def test_normalize_dedupes_and_orders(given: list[str], expected: list[str]) -> None:
    assert normalize_platform_roles(given) == expected


@pytest.mark.parametrize("bad", [["ROOT"], ["manager"], ["MANAGER", "admin"], [""]])
def test_normalize_rejects_foreign_codes(bad: list[str]) -> None:
    with pytest.raises(ValueError, match="unknown"):
        normalize_platform_roles(bad)


@pytest.mark.parametrize(
    ("given", "expected"),
    [(None, None), ("", None), ("   ", None), ("  Главный инженер ", "Главный инженер")],
)
def test_position_is_trimmed_and_blank_is_none(given: str | None, expected: str | None) -> None:
    assert normalize_position(given) == expected


def test_position_limit_is_120_characters() -> None:
    assert normalize_position("я" * 120) == "я" * 120
    with pytest.raises(ValueError, match="120"):
        normalize_position("я" * 121)


def test_users_read_grants_follow_the_admin_row_of_the_matrix() -> None:
    """CRM-01c: чтение сотрудников — роли с `admin: read` (DIRECTOR); ADMIN (full) — `admin` CRM."""
    spec = yaml.safe_load(RBAC.read_text(encoding="utf-8"))
    row = next(r for r in spec["resources"] if r["key"] == "admin")["access"]

    readers = {code for code, level in row.items() if level == "read"}

    assert readers == {code for code, grants in PLATFORM_ROLE_GRANTS.items() if grants}
    assert set(PLATFORM_ROLE_GRANTS) <= set(generated.PLATFORM_ROLE_CODES)
    assert platform_grants(["DIRECTOR", "SUPPLY"]) == {("users", "read")}
    assert platform_grants(["SUPPLY", "ENGINEER", "MANAGER", "ACCOUNTANT", "ADMIN", "x"]) == set()
