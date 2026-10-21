"""Роли ERP, выдаваемые из CRM (FIX-63, Q-FIX50-1 (1)): коды = контракт и каталог ERP."""

import ast
from pathlib import Path

import pytest
import yaml

from app.domain.erp_roles import ERP_ROLE_CODES, normalize_erp_roles

REPO = Path(__file__).resolve().parents[6]
CONTRACT = REPO / "packages" / "contracts" / "openapi" / "erp-integration.yaml"
ERP_CATALOG = REPO / "apps" / "erp" / "backend" / "accounts" / "constants.py"


def _contract_codes() -> list[str]:
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return list(spec["components"]["schemas"]["SystemRoleCode"]["enum"])


def _erp_codes() -> list[str]:
    """Значения `class BackofficeRoleCode(models.TextChoices)` из кода ERP."""
    tree = ast.parse(ERP_CATALOG.read_text(encoding="utf-8"))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BackofficeRoleCode"
    )
    codes: list[str] = []
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Tuple):
            first = stmt.value.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                codes.append(first.value)
    return codes


def test_codes_equal_the_contract_snapshot() -> None:
    assert list(ERP_ROLE_CODES) == _contract_codes()


def test_codes_equal_the_erp_catalog() -> None:
    assert sorted(ERP_ROLE_CODES) == sorted(_erp_codes())


def test_contract_property_is_optional_and_refers_to_the_snapshot() -> None:
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    request = spec["components"]["schemas"]["ProvisionUserRequest"]
    assert "role_codes" not in request["required"]
    assert request["properties"]["role_codes"]["items"] == {
        "$ref": "#/components/schemas/SystemRoleCode"
    }


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ([], []),
        (["HEAD", "CALCULATION"], ["CALCULATION", "HEAD"]),  # порядок каталога
        (["FINANCE", "FINANCE", "FINANCE"], ["FINANCE"]),
        (("VIEWER",), ["VIEWER"]),
    ],
)
def test_normalize_dedupes_and_orders(given: list[str], expected: list[str]) -> None:
    assert normalize_erp_roles(given) == expected


@pytest.mark.parametrize("bad", [["ROOT"], ["head"], ["HEAD", "admin"], [""]])
def test_normalize_rejects_foreign_codes(bad: list[str]) -> None:
    with pytest.raises(ValueError, match="unknown"):
        normalize_erp_roles(bad)
