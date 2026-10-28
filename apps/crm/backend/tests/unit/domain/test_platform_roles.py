"""Каталог возможностей Платформы (R-1, ADR-0012): модуль = каталог, каждый элемент каталога,
объединение ролей, базовая роль CRM для старого фронта, проверка черновика роли."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from app.domain import platform_roles_generated as generated
from app.domain.erp_permissions import ERP_PERMISSIONS, ErpAccess
from app.domain.platform_roles import (
    LEGACY_ROLE_CODES,
    RoleGrant,
    check_spec,
    crm_policies,
    default_roles,
    derive_access,
    diff_access,
    erp_access_for,
    erp_permissions_for,
    legacy_code,
    merge_access,
    normalize_position,
    role_code_for,
    role_crm_base,
)
from app.security.rbac import CATALOG
from tests.platform_role_data import make_grant, make_role

REPO = Path(__file__).resolve().parents[6]
CONTRACTS = REPO / "packages" / "contracts"
RBAC = CONTRACTS / "platform-rbac.yaml"
# Снимок версии 1 (шесть ролей кодом) — в фикстурах тестов: из контракта она удалена (R-2).
RBAC_V1 = Path(__file__).resolve().parents[2] / "fixtures" / "platform_rbac_v1_matrix.yaml"
SCHEMA = CONTRACTS / "platform-rbac.schema.json"
SEAM = CONTRACTS / "openapi" / "erp-integration.yaml"
GENERATOR = REPO / "apps" / "crm" / "scripts" / "gen_platform_roles.py"
GENERATED = REPO / "apps" / "crm" / "backend" / "app" / "domain" / "platform_roles_generated.py"


def _spec() -> dict[str, Any]:
    spec: dict[str, Any] = yaml.safe_load(RBAC.read_text(encoding="utf-8"))
    return spec


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_platform_roles", GENERATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seam_permissions() -> set[str]:
    schemas = yaml.safe_load(SEAM.read_text(encoding="utf-8"))["components"]["schemas"]
    return set(schemas["ErpPermission"]["enum"])


def _crm_permissions() -> set[str]:
    return {f"{res}:{act}" for res, acts in CATALOG.items() for act in acts}


# --- модуль = каталог ---------------------------------------------------------------------------


def test_generated_module_is_exactly_what_the_generator_renders_from_the_catalog() -> None:
    assert GENERATED.read_text(encoding="utf-8") == _generator().render(_spec())


def test_generator_check_mode_passes_on_a_fresh_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["gen_platform_roles.py", "--check"])
    assert _generator().main() == 0


def test_generated_values_equal_the_catalog() -> None:
    spec = _spec()
    resources = {r["key"]: r for r in spec["resources"]}
    assert list(generated.RESOURCE_KEYS) == list(resources)
    for key, res in resources.items():
        assert generated.RESOURCE_LEVELS[key] == tuple(res.get("levels", ["read", "full"]))
        for system, table in (
            ("crm", generated.CRM_BACKEND),
            ("erp", generated.ERP_BACKEND),
            ("eds", generated.EDS_BACKEND),
        ):
            lists = res.get("backend", {}).get(system, {})
            assert {lv: list(v) for lv, v in table[key].items()} == lists
    assert list(generated.SYSTEM_ROLE_CODES) == list(spec["system_roles"])
    assert list(generated.TEMPLATE_ROLE_CODES) == list(spec["templates"])
    assert list(generated.CRM_BASE_ROLE_BY_CODE) == list(LEGACY_ROLE_CODES)


# --- целостность каталога -----------------------------------------------------------------------


def test_every_erp_code_in_the_catalog_is_in_the_seam_permission_list() -> None:
    seam = _seam_permissions()
    assert set(ERP_PERMISSIONS) == seam
    used = {p for table in generated.ERP_BACKEND.values() for ps in table.values() for p in ps}
    used |= {p for ps in generated.FIELD_ERP_BACKEND.values() for p in ps}
    assert used <= seam


def test_every_crm_right_in_the_catalog_is_in_the_casbin_catalog_of_the_code() -> None:
    used = {p for table in generated.CRM_BACKEND.values() for ps in table.values() for p in ps}
    assert used <= _crm_permissions()


def test_contract_schema_enums_equal_the_seam_and_the_code_catalog() -> None:
    defs = json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]
    assert set(defs["erpPermission"]["enum"]) == _seam_permissions()
    assert set(defs["crmPermission"]["enum"]) == _crm_permissions()


def test_full_level_lists_repeat_the_read_level() -> None:
    for table in (generated.CRM_BACKEND, generated.ERP_BACKEND, generated.EDS_BACKEND):
        for key, levels in table.items():
            if "read" in levels and "full" in levels:
                assert set(levels["read"]) <= set(levels["full"]), key


def test_roles_menu_and_queue_refer_only_to_catalog_resources() -> None:
    spec = _spec()
    keys = set(generated.RESOURCE_KEYS)
    for code, role in {**spec["system_roles"], **spec["templates"]}.items():
        for resource, level in role["access"].items():
            assert resource in keys, (code, resource)
            assert level in generated.RESOURCE_LEVELS[resource], (code, resource)
        assert set(role["restricted_fields"]) <= set(spec["restricted_fields"]), code
    for module in spec["menu"].values():
        for resources in module.values():
            assert set(resources) <= keys
    for kind, need in spec["queue"].items():
        assert need["resource"] in keys, kind
        assert need["level"] in generated.RESOURCE_LEVELS[need["resource"]], kind
    for conditions in generated.CRM_BASE_ROLE_BY_ACCESS.values():
        for condition in conditions:
            resource, _, level = condition.partition(":")
            assert level in generated.RESOURCE_LEVELS[resource]


def test_queue_kinds_equal_the_bff_contract() -> None:
    bff = yaml.safe_load((CONTRACTS / "openapi" / "platform-bff.yaml").read_text(encoding="utf-8"))
    assert set(_spec()["queue"]) == set(bff["components"]["schemas"]["QueueItemKind"]["enum"])


# --- каждый элемент каталога: раздел × уровень -> права CRM и ERP ------------------------------

LEADS_READ = {"leads:read", "stream:read", "dashboard:read", "kb:read"}
LEADS_FULL = LEADS_READ | {
    "leads:take",
    "leads:work",
    "leads:reply",
    "leads:note",
    "leads:assist",
    "leads:create",
    "reply_templates:read",
}
CLIENTS_READ = {"clients:read", "deals:read", "documents:read"}
CLIENTS_FULL = CLIENTS_READ | {"clients:write", "deals:write", "documents:write"}
ADMIN_READ = {
    "users:read",
    "integrations:read",
    "models:read",
    "system:read",
    "external_services:read",
    "backups:read",
    "audit:read",
    # W13-A5: директор читает настройки бота, шаблоны ответов и базу знаний (правка — admin: full).
    "settings:read",
    "reply_templates:read",
    "kb:read",
    # W15-H7: директор читает обращения сотрудников, отвечает администратор.
    "tickets:read",
}
ADMIN_FULL = ADMIN_READ | {
    "tickets:write",
    "users:write",
    "settings:read",
    "settings:write",
    "integrations:write",
    "models:read",
    "models:test",
    "models:write",
    "external_services:write",
    "backups:read",
    "backups:write",
    "spend:read",
    "kb:read",
    "kb:write",
    "reply_templates:read",
    "reply_templates:write",
    "sandbox:use",
    "export:read",
}
NOTHING: tuple[set[str], set[str]] = (set(), set())
# (раздел, уровень) -> (права CRM `ресурс:действие`, права ERP). Выписано вручную по ADR-0012 и
# runbook wave9-roles §3.2, независимо от yaml: ловит случайную правку отображения.
EXPECTED: dict[tuple[str, str], tuple[set[str], set[str]]] = {
    ("dashboard.queue", "read"): NOTHING,
    ("dashboard.queue", "full"): NOTHING,
    ("dashboard.summary", "read"): ({"dashboard:read", "spend:read"}, set()),
    ("dashboard.summary", "full"): ({"dashboard:read", "spend:read"}, {"data.export"}),
    ("crm.leads", "read"): (LEADS_READ, set()),
    ("crm.leads", "full"): (LEADS_FULL, set()),
    ("crm.clients", "read"): (CLIENTS_READ, set()),
    # quote.send — отправка одобренного КП клиенту (C1-G-4, решение архитектора 2026-10-26)
    ("crm.clients", "full"): (CLIENTS_FULL, {"deal.manage", "quote.send"}),
    ("eds.inbox", "read"): NOTHING,
    ("eds.inbox", "full"): (set(), {"deal.assign"}),
    ("eds.drafts", "read"): NOTHING,
    ("eds.drafts", "full"): (set(), {"quote.review"}),
    ("eds.projects", "read"): NOTHING,
    ("eds.projects", "full"): (set(), {"contract.manage", "contract.sign", "fulfillment.act"}),
    ("eds.payments", "read"): (set(), {"finance.view"}),  # Q-D2-4-1 п. 2
    (
        "eds.payments",
        "full",
    ): (
        set(),
        {"finance.view", "finance.invoice", "finance.payment", "finance.rates", "data.export"},
    ),
    ("eds.memo.create", "read"): NOTHING,
    ("eds.memo.create", "full"): NOTHING,
    ("eds.memo.approve", "read"): NOTHING,
    ("eds.memo.approve", "full"): NOTHING,
    ("erp.calc", "read"): NOTHING,
    ("erp.calc", "full"): (set(), {"deal.manage", "quote.build", "quote.edit_pricing"}),
    ("erp.calc.goods", "full"): (set(), {"quote.build", "quote.edit_pricing", "quote.visa_goods"}),
    ("erp.calc.services", "full"): (set(), {"quote.build", "quote.visa_services"}),
    ("erp.stock", "read"): NOTHING,
    (
        "erp.stock",
        "full",
    ): (set(), {"catalog.manage", "catalog.publish", "supply.manage", "fulfillment.manage"}),
    ("chats.internal", "read"): NOTHING,
    ("chats.internal", "full"): NOTHING,
    ("chats.external", "read"): ({"leads:read"}, set()),
    (
        "chats.external",
        "full",
    ): ({"leads:read", "leads:reply", "leads:note", "leads:assist"}, set()),
    ("company.settings", "read"): NOTHING,
    ("company.settings", "full"): (set(), {"settings.edit", "settings.charge_templates"}),
    ("admin", "read"): (ADMIN_READ, set()),
    (
        "admin",
        "full",
    ): (ADMIN_FULL, {"team.manage"}),
}


def test_expectation_table_covers_every_catalog_element() -> None:
    elements = {(k, lv) for k in generated.RESOURCE_KEYS for lv in generated.RESOURCE_LEVELS[k]}
    assert set(EXPECTED) == elements


@pytest.mark.parametrize(("element", "expected"), list(EXPECTED.items()), ids=lambda v: str(v))
def test_every_catalog_element_gives_the_expected_crm_and_erp_rights(
    element: tuple[str, str], expected: tuple[set[str], set[str]]
) -> None:
    resource, level = element
    crm, erp = expected
    access = {resource: level}
    assert {f"{r}:{a}" for r, a in crm_policies(access)} == crm
    assert set(erp_permissions_for(access, ())) == erp
    derived = derive_access([RoleGrant(access)])
    assert {f"{r}:{a}" for r, a in derived.crm_permissions} == crm
    assert set(derived.erp_permissions) == erp


FIELDS = {
    "cost_margin": {"quote.view_cost_margin"},
    "supplier_prices": set(),
    "totals_only": set(),
}


@pytest.mark.parametrize(("name", "erp"), list(FIELDS.items()))
def test_every_restricted_field_gives_the_expected_erp_rights(name: str, erp: set[str]) -> None:
    assert set(erp_permissions_for({}, [name])) == erp
    assert set(generated.FIELD_ERP_BACKEND) == set(FIELDS)


# --- системные роли и шаблоны -------------------------------------------------------------------

# Права ERP целых ролей, выписанные вручную.
# Команду ведёт только администратор; счета директор читает (`finance.view`), но не выставляет
# и не фиксирует оплаты (D2-4).
DIRECTOR_ERP = set(ERP_PERMISSIONS) - {
    "team.manage",
    "finance.invoice",
    "finance.payment",
    "finance.rates",
}
ROLE_ERP: dict[str, set[str]] = {
    "MANAGER": {"deal.manage", "quote.send", "finance.view"},
    "DIRECTOR": DIRECTOR_ERP,
    "SUPPLY": {
        "deal.manage",
        "quote.build",
        "quote.edit_pricing",
        "quote.view_cost_margin",
        "quote.visa_goods",
        "catalog.manage",
        "catalog.publish",
        "supply.manage",
        "fulfillment.manage",
    },
    "ENGINEER": {
        "deal.manage",
        "quote.build",
        "quote.edit_pricing",
        "quote.visa_services",
        "catalog.manage",
        "catalog.publish",
        "supply.manage",
        "fulfillment.manage",
    },
    "ACCOUNTANT": {
        "contract.manage",
        "contract.sign",
        "fulfillment.act",
        "finance.view",
        "finance.invoice",
        "finance.payment",
        "finance.rates",
        "data.export",
    },
    "ADMIN": {"team.manage", "settings.edit", "settings.charge_templates"},
}
# Базовая роль CRM — признак по матрице (D1-8, B-014): «Бухгалтер» без `crm.leads` — viewer, а не
# manager, как в версии 1 каталога (по коду роли).
ROLE_BASE = {
    "MANAGER": "manager",
    "DIRECTOR": "viewer",
    "SUPPLY": "viewer",
    "ENGINEER": "viewer",
    "ACCOUNTANT": "viewer",
    "ADMIN": "admin",
}


@pytest.mark.parametrize("legacy", list(ROLE_ERP))
def test_every_system_role_and_template_derives_the_expected_rights(legacy: str) -> None:
    derived = derive_access([make_grant(legacy)])

    assert set(derived.erp_permissions) == ROLE_ERP[legacy]
    assert [p for p in ERP_PERMISSIONS if p in ROLE_ERP[legacy]] == list(derived.erp_permissions)
    assert derived.crm_role == ROLE_BASE[legacy]
    assert derived.platform_access == ("crm", "erp")
    assert derived.erp_role_codes == ()  # системные роли ERP больше не выдаются
    access = erp_access_for([make_grant(legacy)])
    if legacy == "ADMIN":
        assert (access.role, access.permissions) == ("admin", ERP_PERMISSIONS)
    else:
        assert (access.role, set(access.permissions)) == ("backoffice", ROLE_ERP[legacy])


def test_the_two_system_roles_are_fixed_by_the_catalog() -> None:
    rows = {r["code"]: r for r in default_roles()}
    assert rows["ADMIN"]["access"] == {
        "admin": "full",
        "company.settings": "full",
        "dashboard.queue": "full",
        "chats.internal": "full",
        "eds.memo.create": "full",
    }
    director = dict(make_role("DIRECTOR").access)
    # R-1b (уточнение ADR-0012 п. 2): воронка и внешняя переписка — только чтение, лиды не берёт.
    # D2-4: «Счета и оплаты» тоже чтение — оплату подтверждает бухгалтер.
    read_only = {"admin", "crm.leads", "chats.external", "eds.payments"}
    assert {k for k, v in director.items() if v == "read"} == read_only
    assert {k: v for k, v in director.items() if k not in read_only} == {
        k: "full" for k in generated.RESOURCE_KEYS if k not in read_only
    }
    assert rows["DIRECTOR"]["restricted_fields"] == ["cost_margin", "supplier_prices"]
    assert rows["ADMIN"]["is_system"] is True
    assert rows["DIRECTOR"]["is_system"] is True
    assert [r["code"] for r in default_roles() if not r["is_system"]] == [
        "tpl:MANAGER",
        "tpl:SUPPLY",
        "tpl:ENGINEER",
        "tpl:ACCOUNTANT",
    ]


def test_director_sees_leads_but_cannot_take_or_reply() -> None:
    """R-1b: директору — лиды на чтение (воронка, переписка), без `leads:take|reply|work|note`."""
    crm = {f"{res}:{act}" for res, act in derive_access([make_grant("DIRECTOR")]).crm_permissions}

    assert {"leads:read", "stream:read", "clients:write"} <= crm
    assert not crm & {"leads:take", "leads:reply", "leads:work", "leads:note", "leads:assist"}
    assert not crm & {"leads:create"}


def test_director_reads_integrations_models_and_backups_but_changes_nothing() -> None:
    """W13-A1: «Внешние интеграции» на чтение — и модели, и бэкапы; записи и проб нет."""
    crm = {f"{res}:{act}" for res, act in derive_access([make_grant("DIRECTOR")]).crm_permissions}

    assert {
        "integrations:read",
        "external_services:read",
        "system:read",
        "models:read",
        "backups:read",
        "spend:read",
    } <= crm
    assert not crm & {
        "integrations:write",
        "external_services:write",
        "models:write",
        "models:test",
        "backups:write",
    }


def test_a_second_role_with_leads_full_gives_the_director_the_lead_rights_back() -> None:
    """Директору, который сам ведёт лиды, администратор выдаёт вторую роль (объединение прав)."""
    merged = derive_access([make_grant("DIRECTOR"), make_grant("MANAGER")]).crm_permissions

    assert {("leads", "take"), ("leads", "reply")} <= set(merged)


def _v1_columns() -> dict[str, dict[str, str]]:
    v1 = yaml.safe_load(RBAC_V1.read_text(encoding="utf-8"))
    columns: dict[str, dict[str, str]] = {code: {} for code in LEGACY_ROLE_CODES}
    for res in v1["resources"]:
        for code, level in res["access"].items():
            if level != "hidden":
                columns[code][res["key"]] = level
    return columns


@pytest.mark.parametrize("legacy", ["MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
def test_templates_keep_the_v1_matrix_column_plus_the_new_calc_sections(legacy: str) -> None:
    """Шаблоны = колонки матрицы SPEC-v3 §4.2 (версия 1) + виза расчёта у снабженца и инженера."""
    added = {"SUPPLY": {"erp.calc.goods": "full"}, "ENGINEER": {"erp.calc.services": "full"}}
    expected = {**_v1_columns()[legacy], **added.get(legacy, {})}
    assert dict(make_grant(legacy).access) == expected


def test_director_keeps_everything_v1_gave_and_gains_full_where_it_had_read() -> None:
    """Версия 2 (ADR-0012, R-1b): директор — как в v1, full там, где было read; лиды и внешние
    чаты остаются на чтении, Admin — read."""
    v1 = _v1_columns()["DIRECTOR"]
    v2 = dict(make_grant("DIRECTOR").access)
    assert all(v2[k] == v1[k] or (v1[k] == "read" and v2[k] == "full") for k in v1)
    raised = {k for k in v1 if v1[k] != v2[k]}
    # D2-4: `eds.payments` у директора остаётся на чтении, как в v1
    assert raised == {"crm.clients"}
    assert set(v2) - set(v1) == {"erp.calc.goods", "erp.calc.services", "company.settings"}


# --- объединение ролей --------------------------------------------------------------------------


def test_union_takes_the_maximum_level_per_section_and_the_union_of_fields() -> None:
    merged = merge_access(
        [
            RoleGrant({"crm.leads": "read", "eds.payments": "full"}, ("totals_only",)),
            RoleGrant({"crm.leads": "full", "eds.inbox": "read"}, ("cost_margin",)),
        ]
    )
    assert merged == {"crm.leads": "full", "eds.inbox": "read", "eds.payments": "full"}
    derived = derive_access(
        [
            RoleGrant({"eds.payments": "full"}, ("totals_only",)),
            RoleGrant({"crm.leads": "read"}, ("cost_margin",)),
        ]
    )
    assert derived.restricted_fields == ("cost_margin", "totals_only")
    assert set(derived.erp_permissions) == {
        "finance.view",
        "finance.invoice",
        "finance.payment",
        "finance.rates",
        "data.export",
        "quote.view_cost_margin",
    }


def test_manager_plus_accountant_is_the_union_of_their_rights() -> None:
    derived = derive_access([make_grant("MANAGER"), make_grant("ACCOUNTANT")])

    assert derived.crm_role == "manager"
    assert derived.access["crm.leads"] == "full"  # от менеджера
    assert derived.access["eds.payments"] == "full"  # от бухгалтера
    assert derived.access["eds.projects"] == "full"  # максимум: менеджер read, бухгалтер full
    assert derived.restricted_fields == ("totals_only",)
    assert set(derived.erp_permissions) == ROLE_ERP["MANAGER"] | ROLE_ERP["ACCOUNTANT"]
    assert crm_policies(make_grant("MANAGER").access) <= derived.crm_permissions


def test_the_senior_crm_role_wins_and_admin_is_the_erp_superuser() -> None:
    assert derive_access([make_grant("DIRECTOR"), make_grant("SUPPLY")]).crm_role == "viewer"
    assert derive_access([make_grant("DIRECTOR"), make_grant("MANAGER")]).crm_role == "manager"
    both = [make_grant("ADMIN"), make_grant("DIRECTOR")]
    assert derive_access(both).crm_role == "admin"
    access = erp_access_for(both)
    assert (access.role, access.permissions) == ("admin", ERP_PERMISSIONS)


def test_a_custom_role_with_full_admin_is_not_the_erp_superuser() -> None:
    """Q-R1c-1 п. 5 (архитектор, 2026-10-26): суперпользователь ERP — только системная роль
    «Администратор». Пользовательская роль с `admin: full` остаётся администратором CRM (базовая
    роль `admin`), а в ERP получает права своих разделов по каталогу."""
    custom = RoleGrant({"admin": "full", "company.settings": "full"}, (), None)

    assert derive_access([custom]).crm_role == "admin"
    access = erp_access_for([custom])
    assert access.role == "backoffice"
    assert set(access.permissions) == {"team.manage", "settings.edit", "settings.charge_templates"}
    assert erp_access_for([custom, make_grant("MANAGER")]).role == "backoffice"
    # Системная роль по-прежнему суперпользователь, в том числе вместе с пользовательской.
    assert erp_access_for([custom, make_grant("ADMIN")]) == ErpAccess("admin", ERP_PERMISSIONS)


def test_a_custom_role_named_like_a_system_code_is_not_the_admin() -> None:
    """Суперпользователя даёт код системной роли, а не название или раздел."""
    fake = RoleGrant(dict(make_grant("ADMIN").access), (), "tpl:ADMIN")

    assert erp_access_for([fake]).role == "backoffice"


def test_derive_is_independent_of_order() -> None:
    a, b = make_grant("ENGINEER"), make_grant("SUPPLY")
    assert derive_access([a, b]) == derive_access([b, a])


def test_empty_set_has_no_derived_access() -> None:
    with pytest.raises(ValueError, match="empty"):
        derive_access([])


# --- базовая роль CRM для старого фронта --------------------------------------------------------


@pytest.mark.parametrize(
    ("access", "expected"),
    [
        ({"admin": "full"}, "admin"),
        ({"admin": "read"}, "viewer"),
        ({"crm.leads": "full"}, "manager"),
        ({"crm.leads": "read", "chats.external": "full"}, "viewer"),
        ({"crm.clients": "full", "eds.payments": "full"}, "viewer"),
        ({"admin": "full", "crm.leads": "full"}, "admin"),
        ({}, "viewer"),
    ],
)
def test_role_without_a_code_gets_the_base_role_from_its_matrix(
    access: dict[str, str], expected: str
) -> None:
    assert role_crm_base(RoleGrant(access, code=None)) == expected


def test_base_role_follows_the_matrix_not_the_role_code() -> None:
    """D1-8: код роли признака не задаёт — отредактированный шаблон «Менеджер» без `crm.leads`
    перестаёт быть менеджером, а «Бухгалтер» не был им и в каталоге."""
    assert role_crm_base(RoleGrant({}, code="tpl:MANAGER")) == "viewer"
    assert role_crm_base(RoleGrant({}, code="tpl:ACCOUNTANT")) == "viewer"
    assert role_crm_base(RoleGrant({"crm.leads": "full"}, code="tpl:ACCOUNTANT")) == "manager"
    assert role_crm_base(RoleGrant({"crm.leads": "full"}, code="DIRECTOR")) == "manager"


# --- коды ----------------------------------------------------------------------------------------


def test_legacy_codes_map_to_role_codes_and_back() -> None:
    assert [role_code_for(c) for c in LEGACY_ROLE_CODES] == [
        "tpl:MANAGER",
        "DIRECTOR",
        "tpl:SUPPLY",
        "tpl:ENGINEER",
        "tpl:ACCOUNTANT",
        "ADMIN",
    ]
    assert [legacy_code(role_code_for(c)) for c in LEGACY_ROLE_CODES] == list(LEGACY_ROLE_CODES)
    for foreign in (None, "tpl:ROOT", "MANAGER", "tpl:ADMIN", "ROOT"):
        assert legacy_code(foreign) is None


@pytest.mark.parametrize(
    ("value", "expected"), [(None, None), ("", None), ("  ", None), ("  Инженер  ", "Инженер")]
)
def test_position_is_trimmed_and_empty_means_none(value: str | None, expected: str | None) -> None:
    assert normalize_position(value) == expected


def test_position_limit_is_120() -> None:
    assert normalize_position("я" * 120) == "я" * 120
    with pytest.raises(ValueError, match="longer"):
        normalize_position("я" * 121)


# --- проверка черновика роли --------------------------------------------------------------------


def test_check_spec_returns_the_canonical_form() -> None:
    access, fields = check_spec(
        {"admin": "read", "crm.leads": "full"}, ["totals_only", "cost_margin", "cost_margin"]
    )
    assert list(access) == ["crm.leads", "admin"]  # порядок каталога
    assert fields == ["cost_margin", "totals_only"]


@pytest.mark.parametrize(
    ("access", "fields", "message"),
    [
        ({"crm.nothing": "full"}, [], "unknown resource"),
        ({"crm.leads": "hidden"}, [], "not allowed"),
        ({"crm.leads": "write"}, [], "not allowed"),
        ({"erp.calc.goods": "read"}, [], "not allowed"),  # у раздела только full
        ({}, ["secret_notes"], "unknown restricted fields"),
    ],
)
def test_check_spec_rejects_unknown_sections_levels_and_fields(
    access: dict[str, str], fields: list[str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        check_spec(access, fields)


# --- разница матриц (preview) -------------------------------------------------------------------


def test_diff_lists_what_is_gained_and_lost_with_levels() -> None:
    diff = diff_access(
        {"crm.leads": "full", "crm.clients": "read", "admin": "read"},
        {"crm.leads": "read", "crm.clients": "full", "eds.payments": "read"},
        ["cost_margin"],
        ["totals_only"],
    )
    assert diff.gained == [("crm.clients", "full"), ("eds.payments", "read")]
    assert diff.lost == [("crm.leads", "full"), ("admin", "read")]
    assert (diff.fields_gained, diff.fields_lost) == (["totals_only"], ["cost_margin"])
    assert diff_access({"admin": "full"}, {"admin": "full"}).gained == []
