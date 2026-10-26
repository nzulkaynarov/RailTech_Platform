"""Карта прав CRM → ERP (FIX-11, S-11): каждый код есть в каталоге ERP, менеджеру — минимум."""

import ast
from pathlib import Path

import pytest
import yaml

from app.domain.erp_permissions import ERP_PERMISSIONS, MANAGER_PERMISSIONS, erp_access

REPO = Path(__file__).resolve().parents[6]
CONTRACT = REPO / "packages" / "contracts" / "openapi" / "erp-integration.yaml"
ERP_CATALOG = REPO / "apps" / "erp" / "backend" / "accounts" / "constants.py"


def _contract_permissions() -> list[str]:
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return list(spec["components"]["schemas"]["ErpPermission"]["enum"])


def _erp_catalog() -> list[str]:
    """Значения `class Permission(models.TextChoices)` из кода ERP: `NAME = "code", "label"`."""
    tree = ast.parse(ERP_CATALOG.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Permission")
    codes: list[str] = []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Tuple):
            first = stmt.value.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                codes.append(first.value)
    return codes


def test_contract_snapshot_equals_erp_catalog() -> None:
    """Снимок `ErpPermission` в контракте не расходится с `accounts.constants.Permission` ERP."""
    assert _contract_permissions() == _erp_catalog()


def test_snapshot_in_code_equals_erp_catalog() -> None:
    assert list(ERP_PERMISSIONS) == _erp_catalog()


@pytest.mark.parametrize("roles", [["admin"], ["manager"], ["viewer"], ["manager", "viewer"], []])
def test_every_code_is_in_the_erp_catalog(roles: list[str]) -> None:
    catalog = set(_erp_catalog())
    assert set(erp_access(roles).permissions) <= catalog


def test_old_codes_that_never_existed_in_erp_are_gone() -> None:
    for role in ("admin", "manager", "viewer"):
        codes = set(erp_access([role]).permissions)
        assert not codes & {"quote.view", "quote.edit", "supply.*", "quote.*"}


def test_admin_is_erp_superuser_with_the_whole_catalog() -> None:
    access = erp_access(["admin"])
    assert access.role == "admin"
    assert set(access.permissions) == set(_erp_catalog())


def test_manager_gets_sales_workplace_without_cost_margin_or_finance() -> None:
    access = erp_access(["manager"])
    assert access.role == "backoffice"
    assert set(access.permissions) == set(MANAGER_PERMISSIONS)
    for forbidden in (
        "quote.view_cost_margin",
        "contract.sign",
        "finance.payment",
        "settings.edit",
        "team.manage",
        "data.export",
    ):
        assert forbidden not in access.permissions


def test_viewer_gets_no_permissions() -> None:
    access = erp_access(["viewer"])
    assert access.role == "backoffice"
    assert access.permissions == ()


def test_roles_are_united_and_admin_overrides() -> None:
    assert erp_access(["viewer", "manager"]).permissions == erp_access(["manager"]).permissions
    assert erp_access(["manager", "admin"]).role == "admin"


def test_unknown_roles_grant_nothing() -> None:
    assert erp_access(["root", "superuser"]) == erp_access([])
    assert erp_access([]).permissions == ()


def test_permission_order_is_catalog_order() -> None:
    codes = erp_access(["manager"]).permissions
    assert list(codes) == [c for c in ERP_PERMISSIONS if c in codes]
