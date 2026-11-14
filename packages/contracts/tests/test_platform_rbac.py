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
    "files.upload",
    "signing.manage",
    "approvals.visa_finance",
    "approvals.visa_legal",
}
#: Код журнала шины (W13-A2): только раздел `admin` уровня `full` — у директора (`admin: read`) его нет.
BUS = "bus.manage"
#: Свой файл в EDS (письмо директору к «Создать заявку», D1-2b): раздел `crm.clients` уровня `full`.
UPLOAD = "files.upload"
#: Реестр полномочий подписи (SIGN-2): раздел `eds.signing.manage`, системная роль администратора.
SIGNING = "signing.manage"
#: Визы перед подписью (ADR-0025): бухгалтера — `eds.visa.finance`, юриста — `eds.visa.legal`.
VISA_FINANCE = "approvals.visa_finance"
VISA_LEGAL = "approvals.visa_legal"
#: Публичные операции EDS: без токена доступа и без права.
PUBLIC = {("get", "/health"), ("post", "/api/v1/auth/sso/exchange")}
# Любой активный сотрудник, сужение — внутри операции (P8b, SPEC-v3 §3.2a «Права»: исполнитель видит письмо своего
# поручения без `letters.read`): карточка письма, ознакомление, действия исполнителя и автора резолюции, свои задачи.
ANY_EMPLOYEE = {
    ("get", "/api/v1/me"),
    # Обозначения номеров документооборота (задача «Н2»): образец в настройках видит любой сотрудник
    ("get", "/api/v1/numbering-labels"),
    ("get", "/api/v1/letters/{letter_id}"),
    ("post", "/api/v1/letters/{letter_id}/acquaint"),
    # План 1.9: соисполнителя привлекает ответственный — проверка внутри операции
    ("post", "/api/v1/letters/{letter_id}/co-executors"),
    ("post", "/api/v1/instructions/{instruction_id}/complete"),
    ("post", "/api/v1/instructions/{instruction_id}/extension"),
    ("post", "/api/v1/instructions/{instruction_id}/extension/decision"),
    # Исходы письма (решение владельца 2026-11-11): право решает EDS по роли в поручении и авторству резолюции
    ("post", "/api/v1/letters/{letter_id}/close"),
    ("post", "/api/v1/letters/{letter_id}/reopen"),
    ("post", "/api/v1/instructions/{instruction_id}/return"),
    ("get", "/api/v1/letter-tasks"),
    # P4: бланк компании для формы письма — любой сотрудник (черновик письма создаёт любой с `memos.create`)
    ("get", "/api/v1/letterhead"),
}


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
        ("DIRECTOR", EDS_CODES - {BUS, SIGNING, "payments.confirm", VISA_FINANCE, VISA_LEGAL}),
        ("MANAGER", {"letters.read", "registry.read", "memos.create", UPLOAD}),
        ("SUPPLY", {"registry.read", "memos.create"}),
        ("ENGINEER", {"registry.read", "memos.create"}),
        (
            "ACCOUNTANT",
            {"letters.read", "registry.read", "registry.export", "payments.confirm", "memos.create", VISA_FINANCE},
        ),
        # ADR-0025: юрист визирует договор.
        ("LAWYER", {"letters.read", "registry.read", "memos.create", VISA_LEGAL}),
        # P8: делопроизводитель регистрирует входящие, резолюции не накладывает.
        ("REGISTRAR", {"letters.read", "letters.register", "registry.read", "memos.create"}),
        # P8: менеджер-универсал — договор, счёт, акт, сканы, оплаты; письма только читает.
        (
            "MANAGER_ALL",
            {
                "letters.read",
                "registry.read",
                "registry.export",
                "payments.confirm",
                "memos.create",
                UPLOAD,
                VISA_FINANCE,
            },
        ),
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


def test_director_gets_every_eds_code_except_the_bus_journal_and_the_payment_confirmation() -> None:
    """D2-4 (Q-D2-4-1 п. 1): «Счета и оплаты» у директора — `read`; оплату подтверждает бухгалтер."""
    assert len(EDS_CODES) == 14
    # ADR-0025: директор подписывает, а не визирует — визы бухгалтера и юриста у него нет.
    assert eds_permissions(role("DIRECTOR")) == EDS_CODES - {BUS, SIGNING, "payments.confirm", VISA_FINANCE, VISA_LEGAL}


def test_bus_journal_is_admin_full_only() -> None:
    """W13-A2: «Журнал интеграций» — раздел `admin` уровня `full`; `read` (директор) кода не даёт."""
    assert eds_permissions({"admin": "full"}) == {BUS}
    assert eds_permissions({"admin": "read"}) == set()
    for r in CATALOG["resources"]:
        if r["key"] != "admin":
            assert BUS not in str((r.get("backend") or {}).get("eds")), r["key"]


def test_clients_full_brings_only_the_own_file_upload() -> None:
    """D1-2b (решение архитектора): своя роль только с `crm.clients: full` загружает письмо директору в EDS и читает
    только свои файлы — ни писем, ни реестра, ни документов; уровень `read` кода не даёт."""
    assert eds_permissions({"crm.clients": "full"}) == {UPLOAD}
    assert eds_permissions({"crm.clients": "read"}) == set()
    paths = EDS_YAML["paths"]
    assert UPLOAD in paths["/api/v1/files"]["post"]["x-rt-permissions"]
    assert UPLOAD in paths["/api/v1/files/{file_id}"]["get"]["x-rt-permissions"]
    granted = {
        (path, method)
        for path, ops in paths.items()
        for method, op in ops.items()
        if isinstance(op, dict) and UPLOAD in op.get("x-rt-permissions", [])
    }
    assert granted == {
        ("/api/v1/files", "post"),
        ("/api/v1/files/{file_id}", "get"),
        ("/api/v1/files/{file_id}/versions", "get"),
    }
    for r in CATALOG["resources"]:
        if r["key"] != "crm.clients":
            assert UPLOAD not in str((r.get("backend") or {}).get("eds")), r["key"]


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
    assert got == {"memos.create", BUS, SIGNING}
    assert not got & (EDS_CODES - {"memos.create", BUS, SIGNING})


@pytest.mark.parametrize(
    ("access", "expected"),
    [
        # «Менеджер и бухгалтер» гейта R-3 (создана с нуля): лиды и «Счета и оплаты» — полный доступ.
        # Выгрузка реестра (`registry.export`) — в разделе «Проекты», не в «Счетах и оплатах» (Q-D2-4-1 п. 1).
        ({"crm.leads": "full", "eds.payments": "full"}, {"registry.read", "payments.confirm"}),
        # «Менеджер и бухгалтер (из шаблона)»: матрица «Менеджер» + «Счета и оплаты» full.
        (
            {**CATALOG["templates"]["MANAGER"]["access"], "eds.payments": "full"},
            {"letters.read", "registry.read", "payments.confirm", "memos.create", UPLOAD},
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
    assert bool(perms) != ((method, path) in ANY_EMPLOYEE), "пустой список (любой сотрудник) — только ANY_EMPLOYEE"
    assert path == "/health" or path.startswith("/api/v1/")


def test_eds_api_global_security_is_the_eds_access_token() -> None:
    assert EDS_YAML["security"] == [{"edsAccess": []}]
    scheme = EDS_YAML["components"]["securitySchemes"]["edsAccess"]
    assert (scheme["type"], scheme["scheme"], scheme["bearerFormat"]) == ("http", "bearer", "JWT")
    # 0.21.0 — «Передать в работу»: `handed_to` поручения (план 1.9);
    # 0.19.0 — соисполнители от ответственного (план 1.9);
    # 0.18.0 — визы бухгалтера и юриста маршрута подписи (ADR-0025);
    # 0.17.0 — согласующие от автора и получатели копии документа (пункт 1.6 плана);
    # 0.16.0 — обозначения номеров документооборота `/numbering-labels` (задача «Н2»);
    # 0.15.0 — `stage` реестра («Исходящие» и «Архив») и сумма строки (FR-5);
    # 0.14.0 — «Закрыть без ответа», «Вернуть в работу», «Вернуть автору», справочник close-reasons;
    # 0.13.0 — текст письма из почты в карточке ВХ (`body_text`), ответ закрывает и «К исполнению»;
    # 0.12.0 — маршрут подписи signing и поля signing_* в ApprovalObject (SIGN-4, FX-10);
    # 0.11.0 — код signing.manage в перечне ответов EdsPermission и ресурс /signing (SIGN-2);
    # 0.10.0 — статусы «Дубль» письма и «Отменено» поручения (EDS-DUP);
    # 0.9.0 — способ получения кодом справочника (EDS-REG);
    # 0.8.0 — статусы пути делопроизводства и поручения (P8b); 0.7.0 — договоры, счета, акты в реестре (D2-5);
    # 0.6.0 — код files.upload в перечне ответов EdsPermission (D1-2b);
    # 0.5.0 — зона исполнителя резолюции (D1-8); 0.4.0 — PATCH /documents/{id} (D1-5); 0.3.0 — журнал шины (W13-A2)
    assert EDS_YAML["info"]["version"] == "0.21.0"


# Коды справочников (EDS-REG) — слаги `^[a-z][a-z_-]…$` без «/», поэтому могут быть в пути.
SLUG_PARAMS = {"{kind}": "DictionaryKind", "{code}": "DictionaryCode"}


def test_numbers_are_not_path_parameters() -> None:
    """Номер реестра содержит «/» — в пути только стабильный id (UUID) или слаг справочника."""
    params = EDS_YAML["components"]["parameters"]
    for path in EDS_YAML["paths"]:
        for segment in Path(path).parts:
            if segment in SLUG_PARAMS:
                schema = params[SLUG_PARAMS[segment]]["schema"]
                schema = (
                    EDS_YAML["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]] if "$ref" in schema else schema
                )
                assert schema["pattern"].startswith("^[a-z]") and "/" not in schema["pattern"], path
            elif segment.startswith("{"):
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


# ─── P8: регистрация входящих отдельно от резолюции; роли пилота ─────────────────────────────────────


def test_registering_letters_is_a_separate_section_from_the_resolution() -> None:
    """P8 (аудит UI 2026-10-30 R1, SPEC-v3 §3.2a): `letters.register` даёт только `eds.inbox.register`,
    `letters.resolve` — только `eds.inbox` уровня `full`."""
    givers = {
        code: {
            r["key"]
            for r in CATALOG["resources"]
            for codes in ((r.get("backend") or {}).get("eds") or {}).values()
            if code in codes
        }
        for code in ("letters.register", "letters.resolve")
    }
    assert givers == {"letters.register": {"eds.inbox.register"}, "letters.resolve": {"eds.inbox"}}
    assert eds_permissions({"eds.inbox.register": "full"}) == {"letters.read", "letters.register", "registry.read"}
    assert "letters.resolve" not in eds_permissions({"eds.inbox": "read", "eds.inbox.register": "full"})


def test_every_role_with_the_resolution_also_registers() -> None:
    """P8: кто держал `eds.inbox: full` до разделения, сохраняет регистрацию (каталог и миграция CRM)."""
    for code in {**CATALOG["system_roles"], **CATALOG["templates"]}:
        if role(code).get("eds.inbox") == "full":
            assert role(code).get("eds.inbox.register") == "full", code


def test_pilot_roles_are_four_templates_and_system_roles() -> None:
    """DECISIONS 2026-10-29 W-2: пилот — администратор, директор (системные), делопроизводитель, менеджер-универсал."""
    assert {"REGISTRAR", "MANAGER_ALL"} <= set(CATALOG["templates"])
    assert set(CATALOG["system_roles"]) == {"ADMIN", "DIRECTOR"}
    assert CATALOG["templates"]["REGISTRAR"]["name"]["ru"] == "Делопроизводитель"
    assert CATALOG["templates"]["MANAGER_ALL"]["name"]["ru"] == "Менеджер-универсал"


def test_registrar_is_the_first_line_and_the_all_round_manager_covers_the_back_office() -> None:
    """P8: граница по лидам (DECISIONS 2026-11-01 п. 1) и состав менеджера-универсала (runbook 18a, P8; W-1)."""
    registrar = role("REGISTRAR")
    # D17G-1: лиды — чтение и разбор с передачей менеджеру; «Забрать» и ответ клиенту — менеджер-универсал
    assert registrar["crm.leads"] == "read" and registrar["crm.leads.triage"] == "full"
    assert CATALOG["queue"]["triage_lead"] == {"resource": "crm.leads.triage", "level": "full"}
    assert registrar["crm.clients"] == "read"  # «Создать заявку» — менеджер-универсал
    assert registrar["eds.inbox"] == "read" and registrar["eds.inbox.register"] == "full"
    assert not {"eds.drafts", "eds.payments", "erp.calc", "admin"} & set(registrar)
    manager = role("MANAGER_ALL")
    for key in (
        "crm.leads",
        "crm.clients",
        "eds.projects",
        "eds.payments",
        "erp.calc",
        "erp.calc.goods",
        "erp.calc.services",
        "erp.stock",
        "chats.external",
    ):
        assert manager[key] == "full", key
    assert manager["eds.inbox"] == "read" and "eds.inbox.register" not in manager
    assert manager.get("eds.drafts") == "read" and "eds.memo.approve" not in manager
