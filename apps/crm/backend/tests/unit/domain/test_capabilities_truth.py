"""«Что может человек» (ДОСТ-1): коды, по которым Платформа показывает возможности, совпадают с тем,
что CRM выдаёт и проверяет на самом деле.

Платформа (BFF) считает «действие включено» по таблицам «раздел → уровень → коды» из своего
сгенерированного каталога. Здесь те же роли прогоняются через настоящее вычисление CRM
(`derive_access`, `erp_access_for`, `eds_permissions_for`) и настоящую проверку casbin
(`Rbac.allowed`): наборы кодов совпадают целиком — экран не назовёт возможностью то, что CRM не
выдала, и не спрячет то, что выдала.
"""

import importlib.util
import itertools
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.config import Settings
from app.domain.platform_roles import (
    RoleGrant,
    default_roles,
    derive_access,
    eds_permissions_for,
    erp_access_for,
    role_subject,
)
from app.security.rbac import CATALOG, Rbac, read_seed

CASBIN_DIR = Settings(_env_file=None).casbin_dir
REPO = Path(__file__).resolve().parents[6]
BFF_DATA = REPO / "apps" / "platform" / "bff" / "app" / "capabilities_generated.py"


def _bff_data() -> dict[str, Any]:
    """Каталог BFF читается по пути: у BFF свой пакет `app`, импортом его не взять."""
    spec = importlib.util.spec_from_file_location("bff_capabilities_generated", BFF_DATA)
    assert spec is not None
    assert spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data: dict[str, Any] = module.DATA
    return data


DATA = _bff_data()
ROLES: dict[str, dict[str, Any]] = {row["code"]: row for row in default_roles()}  # type: ignore[misc]
ROLE_ID = {code: index + 1 for index, code in enumerate(ROLES)}


def _grant(code: str) -> RoleGrant:
    row = ROLES[code]
    return RoleGrant(dict(row["access"]), tuple(row["restricted_fields"]), code)


def _casbin(codes: list[str]) -> Rbac:
    rules = read_seed(CASBIN_DIR / "policy.seed.csv")
    for code in codes:
        grant = _grant(code)
        for resource, action in sorted(derive_access([grant]).crm_permissions):
            rules.append([role_subject(ROLE_ID[code]), "crm", resource, action])
    return Rbac.from_rules(CASBIN_DIR, rules)


RBAC = _casbin(list(ROLES))
COMBOS = [(code,) for code in ROLES] + list(itertools.combinations(list(ROLES)[:6], 2))


def _bff_codes(codes: tuple[str, ...]) -> dict[str, set[str]]:
    """Коды, как их считает BFF: максимум по разделу, таблицы каталога, поля, суперпользователь."""
    access: dict[str, str] = {}
    fields: set[str] = set()
    for code in codes:
        row = ROLES[code]
        fields |= set(row["restricted_fields"])
        for resource, level in row["access"].items():
            if level == "full" or access.get(resource) is None:
                access[resource] = level
    out: dict[str, set[str]] = {"crm": set(), "erp": set(), "eds": set()}
    for resource, level in access.items():
        for backend, per_level in DATA["section_codes"].get(resource, {}).items():
            out[backend].update(per_level.get(level, ()))
    for name in fields:
        out["erp"].update(DATA["field_erp"].get(name, ()))
    if any(ROLES[c]["is_system"] and c == "ADMIN" for c in codes):
        out["erp"].update(DATA["erp_all"])
    return out


@pytest.mark.parametrize("codes", COMBOS, ids="+".join)
def test_bff_code_tables_equal_what_crm_grants(codes: tuple[str, ...]) -> None:
    grants = [_grant(c) for c in codes]
    bff = _bff_codes(codes)
    derived = derive_access(grants)

    assert bff["erp"] == set(erp_access_for(grants).permissions)
    assert bff["eds"] == set(eds_permissions_for(derived.access))
    assert bff["crm"] == {f"{r}:{a}" for r, a in derived.crm_permissions}


@pytest.mark.parametrize("codes", COMBOS, ids="+".join)
def test_bff_crm_codes_equal_the_real_casbin_decision(codes: tuple[str, ...]) -> None:
    """Для каждого из 51 права CRM: BFF говорит «есть» ⇔ casbin разрешает по ролям сотрудника."""
    bff = _bff_codes(codes)["crm"]
    ids = [ROLE_ID[c] for c in codes]
    for resource, actions in CATALOG.items():
        for action in actions:
            assert (f"{resource}:{action}" in bff) == RBAC.allowed([], resource, action, ids), (
                codes,
                resource,
                action,
            )


def test_every_crm_code_a_capability_names_is_in_the_crm_catalog() -> None:
    catalog = {f"{r}:{a}" for r, acts in CATALOG.items() for a in acts}
    named = {
        code
        for cap in DATA["capabilities"]
        for level in cap["levels"]
        for action in level["actions"]
        for code in action.get("crm", ())
    }
    assert named <= catalog
    assert catalog - named == set()  # ни одно право CRM не осталось без строки на экране
