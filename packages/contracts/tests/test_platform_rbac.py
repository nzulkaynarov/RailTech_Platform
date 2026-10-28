"""Каталог возможностей (platform-rbac.yaml) → права EDS (волна 12, runbook §2.2): отображение ролей в коды EDS.

Правило вычисления — как для ERP (ADR-0012 п. 5): права сотрудника = объединение по разделам его ролей; уровень `full`
раздела включает права уровня `read`. Тот же расчёт делает CRM (задача E4) и публикует `user.permissions.eds`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from contracts_events import CONTRACTS

CATALOG: dict[str, Any] = yaml.safe_load((CONTRACTS / "platform-rbac.yaml").read_text(encoding="utf-8"))
EDS_YAML: dict[str, Any] = yaml.safe_load((CONTRACTS / "openapi" / "eds.yaml").read_text(encoding="utf-8"))

EDS_CODES = {
    "letters.read",
    "letters.register",
    "letters.resolve",
    "memos.create",
    "memos.approve",
    "approvals.decide",
    "registry.read",
    "registry.export",
    "payments.confirm",
    "bus.manage",
}
#: Код журнала шины (W13-A2): только раздел `admin` уровня `full` — у директора (`admin: read`) его нет.
BUS = "bus.manage"
#: Публичные операции EDS: без токена доступа и без права.
PUBLIC = {("get", "/health"), ("post", "/api/v1/auth/sso/exchange")}


def eds_permissions(access: dict[str, str]) -> set[str]:
    """Права EDS по объединённой матрице доступа (раздел → full|read)."""
    backend = {r["key"]: (r.get("backend") or {}).get("eds") or {} for r in CATALOG["resources"]}
    codes: set[str] = set()
    for key, level in access.items():
        lists = backend[key]
        codes.update(lists.get("read", ()))
        if level == "full":
            codes.update(lists.get("full", ()))
    return codes


def role(code: str) -> dict[str, str]:
    roles = {**CATALOG["system_roles"], **CATALOG["templates"]}
    return dict(roles[code]["access"])


def test_catalog_codes_are_exactly_the_eds_v1_codes() -> None:
    used: set[str] = set()
    for r in CATALOG["resources"]:
        for codes in ((r.get("backend") or {}).get("eds") or {}).values():
            used.update(codes)
    assert used == EDS_CODES, "каждый код v1 даёт хотя бы один раздел, других кодов нет"
    assert set(EDS_YAML["components"]["schemas"]["EdsPermission"]["enum"]) == EDS_CODES


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("DIRECTOR", EDS_CODES - {BUS}),
        ("MANAGER", {"letters.read", "registry.read", "memos.create"}),
        ("SUPPLY", {"registry.read", "memos.create"}),
        ("ENGINEER", {"registry.read", "memos.create"}),
        ("ACCOUNTANT", {"letters.read", "registry.read", "registry.export", "payments.confirm", "memos.create"}),
    ],
)
def test_system_roles_and_templates_map_to_their_eds_codes(code: str, expected: set[str]) -> None:
    assert eds_permissions(role(code)) == expected


def test_rework_row_belongs_to_the_author_of_documents_not_to_the_approver() -> None:
    """D1-6b: строка «Доработать» очереди (`rework_document`) — раздел `eds.memo.create` уровня `full`, то есть право
    автора `memos.create` (EDS отдаёт автору его возвращённые документы); право согласующего её не даёт."""
    rule = CATALOG["queue"]["rework_document"]
    assert (rule["resource"], rule["level"]) == ("eds.memo.create", "full")
    memos_create = {
        r["key"]
        for r in CATALOG["resources"]
        if "memos.create" in ((r.get("backend") or {}).get("eds") or {}).get("full", ())
    }
    assert rule["resource"] in memos_create
    assert rule["resource"] != "eds.memo.approve"
    holders = {
        code
        for code in {**CATALOG["system_roles"], **CATALOG["templates"]}
        if role(code).get(rule["resource"]) == "full"
    }
    assert {"ADMIN", "DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"} <= holders


def test_director_gets_every_eds_code_except_the_bus_journal() -> None:
    assert len(EDS_CODES) == 10
    assert eds_permissions(role("DIRECTOR")) == EDS_CODES - {BUS}


def test_bus_journal_is_admin_full_only() -> None:
    """W13-A2: «Журнал интеграций» — раздел `admin` уровня `full`; `read` (директор) кода не даёт."""
    assert eds_permissions({"admin": "full"}) == {BUS}
    assert eds_permissions({"admin": "read"}) == set()
    for r in CATALOG["resources"]:
        if r["key"] != "admin":
            assert BUS not in str((r.get("backend") or {}).get("eds")), r["key"]


def test_accountant_step_of_a_memo_is_decided_with_payments_confirm() -> None:
    """Решение архитектора (волна 12): шаг «бухгалтер» служебной записки с суммой — `payments.confirm`.

    `registry.export` для этого не используется.
    """
    decision = EDS_YAML["paths"]["/api/v1/approvals/{approval_id}/decision"]["post"]
    assert "payments.confirm" in decision["x-rt-permissions"]
    assert "registry.export" not in decision["x-rt-permissions"]


def test_administrator_sees_no_business_documents() -> None:
    """R3-D-2: системный «Администратор» бизнес-документов не видит — ни писем, ни реестра, ни маршрутов.

    Права — `memos.create` (раздел `eds.memo.create` у роли в каталоге): свои служебные записки, как у любого
    сотрудника; чужих документов это право не открывает (eds.yaml: без `registry.read` — только свои и маршруты, где он
    участник) — и `bus.manage` (журнал шины, W13-A2): метаданные доставок без тел событий.
    """
    got = eds_permissions(role("ADMIN"))
    assert got == {"memos.create", BUS}
    assert not got & (EDS_CODES - {"memos.create", BUS})


@pytest.mark.parametrize(
    ("access", "expected"),
    [
        # «Менеджер и бухгалтер» гейта R-3 (создана с нуля): лиды и «Счета и оплаты» — полный доступ.
        ({"crm.leads": "full", "eds.payments": "full"}, {"registry.read", "registry.export", "payments.confirm"}),
        # «Менеджер и бухгалтер (из шаблона)»: матрица «Менеджер» + «Счета и оплаты» full.
        (
            {**CATALOG["templates"]["MANAGER"]["access"], "eds.payments": "full"},
            {"letters.read", "registry.read", "registry.export", "payments.confirm", "memos.create"},
        ),
    ],
    ids=["manager-and-accountant", "manager-and-accountant-from-template"],
)
def test_manager_and_accountant_role_of_the_c1_gate(access: dict[str, str], expected: set[str]) -> None:
    assert eds_permissions(access) == expected


def test_read_level_never_gives_a_writing_code() -> None:
    writing = EDS_CODES - {"letters.read", "registry.read"}
    for r in CATALOG["resources"]:
        read = set(((r.get("backend") or {}).get("eds") or {}).get("read", ()))
        assert not read & writing, r["key"]


def test_full_level_repeats_read_for_readability() -> None:
    for r in CATALOG["resources"]:
        eds = (r.get("backend") or {}).get("eds") or {}
        if "read" in eds and "full" in eds:
            assert set(eds["read"]) <= set(eds["full"]), r["key"]


# ─── eds.yaml: право на каждый эндпоинт ─────────────────────────────────────────────────────────────


def operations() -> list[tuple[str, str, dict[str, Any]]]:
    methods = {"get", "post", "put", "patch", "delete"}
    return [
        (method, path, op)
        for path, item in EDS_YAML["paths"].items()
        for method, op in item.items()
        if method in methods
    ]


@pytest.mark.parametrize(("method", "path", "op"), operations(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_eds_operation_declares_its_permissions(method: str, path: str, op: dict[str, Any]) -> None:
    if (method, path) in PUBLIC:
        assert op.get("security") == [], "публичная операция — без токена"
        assert "x-rt-permissions" not in op
        return
    assert "security" not in op, "защищённая операция — глобальный edsAccess"
    perms = op["x-rt-permissions"]
    assert isinstance(perms, list)
    assert set(perms) <= EDS_CODES
    assert len(perms) == len(set(perms))
    assert perms or path == "/api/v1/me", "пустой список (любой сотрудник) — только /me"
    assert path == "/health" or path.startswith("/api/v1/")


def test_eds_api_global_security_is_the_eds_access_token() -> None:
    assert EDS_YAML["security"] == [{"edsAccess": []}]
    scheme = EDS_YAML["components"]["securitySchemes"]["edsAccess"]
    assert (scheme["type"], scheme["scheme"], scheme["bearerFormat"]) == ("http", "bearer", "JWT")
    assert EDS_YAML["info"]["version"] == "0.4.0"  # 0.4.0 — PATCH /documents/{id} (D1-5); 0.3.0 — журнал шины (W13-A2)


def test_numbers_are_not_path_parameters() -> None:
    """Номер реестра содержит «/» — в пути только стабильный id (UUID)."""
    for path in EDS_YAML["paths"]:
        for segment in Path(path).parts:
            if segment.startswith("{"):
                assert segment.endswith("_id}"), path


def erp_permissions(access: dict[str, str]) -> set[str]:
    """Права ERP по объединённой матрице доступа — то же правило, что для EDS (ADR-0012 п. 5)."""
    backend = {r["key"]: (r.get("backend") or {}).get("erp") or {} for r in CATALOG["resources"]}
    codes: set[str] = set()
    for key, level in access.items():
        lists = backend[key]
        codes.update(lists.get("read", ()))
        if level == "full":
            codes.update(lists.get("full", ()))
    return codes


@pytest.mark.parametrize(
    ("code", "sends"),
    [("DIRECTOR", True), ("MANAGER", True), ("SUPPLY", False), ("ENGINEER", False), ("ACCOUNTANT", False)],
)
def test_approved_quote_is_sent_to_the_client_by_the_manager_and_the_director(code: str, sends: bool) -> None:
    """C1-G-4 (решение архитектора 2026-10-26): `quote.send` отделён от `eds.drafts` и дан разделу `crm.clients` full.

    Отправляют менеджер заявки и директор; автор КП (снабженец), гл. инженер и бухгалтер — нет.
    """
    assert ("quote.send" in erp_permissions(role(code))) is sends


def test_quote_send_comes_only_from_crm_clients_full() -> None:
    holders = {
        (r["key"], level)
        for r in CATALOG["resources"]
        for level, codes in ((r.get("backend") or {}).get("erp") or {}).items()
        if "quote.send" in codes
    }
    assert holders == {("crm.clients", "full")}
    drafts = next(r for r in CATALOG["resources"] if r["key"] == "eds.drafts")
    assert drafts["backend"]["erp"] == {"full": ["quote.review"]}
