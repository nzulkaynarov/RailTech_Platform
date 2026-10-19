"""Сторож контракта портала (FIX-21, находки P-8, C-1): ответы ERP проверяются по `erp-portal.yaml` на каждом прогоне.

Что проверяется для КАЖДОГО GET-эндпоинта портала на фикстурах сущностей во всех статусах:

1. ответ проходит JSON Schema из контракта (`$ref` раскрыты; типы, форматы, enum, `required`, `nullable`);
2. множество ключей любого объекта ⊆ `properties` схемы — контракт без `additionalProperties: false` не значит
   «можно лишнее» (так в ответы просачиваются ставка НДС, внутренние id, `items`-дубли);
3. каждое значение enum статуса, достижимое из модели, встретилось в ответах (иначе статус «не проверен»);
4. тела ошибок — `{"detail": <код из ErrorCode>}`.

Падение сторожа — падение теста: ни `skip`, ни `importorskip`. Контракта на диске нет — тест падает с подсказкой
про монтирование (`apps/erp/scripts/test_backend_local.sh`).
"""

from __future__ import annotations

import re

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from portal.tests.conftest import PortalAPIClient
from portal.tests.contract_support import (
    check_response,
    component,
    contract_get_paths,
    error_codes,
    find_contract_path,
    load_contract,
    response_schema,
    schema_errors,
)
from portal.tests.contract_world import MAGIC_TOKEN

PREFIX = "/api/portal/v1"

pytestmark = pytest.mark.django_db


def pks(items):
    return [item.pk for item in items]


#: Какие URL опрашивает сторож по каждому GET-пути контракта. Новый GET в контракте без строки здесь роняет
#: `test_every_contract_get_is_covered`: новый эндпоинт нельзя добавить, не заведя для него фикстур.
GET_CASES = {
    "/me": lambda w: ["/me"],
    "/requests": lambda w: ["/requests"],
    "/requests/{id}": lambda w: [
        f"/requests/{pk}" for pk in pks([w["new_deal"], w["in_progress"], w["closed"], w["main"]])
    ],
    "/quotes": lambda w: ["/quotes"],
    "/quotes/{id}": lambda w: [f"/quotes/{q.pk}" for q in w["quotes"].values()],
    "/contracts": lambda w: ["/contracts"],
    "/invoices": lambda w: ["/invoices"],
    "/acts": lambda w: ["/acts"],
    "/deliveries": lambda w: ["/deliveries"],
    "/documents": lambda w: ["/documents"],
    "/documents/{id}/file": lambda w: [f"/documents/{d.pk}/file" for d in w["documents"].values()],
    "/catalog/categories": lambda w: ["/catalog/categories"],
    "/catalog": lambda w: ["/catalog"],
    "/catalog/{id}": lambda w: [f"/catalog/{w['product'].pk}"],
    "/company": lambda w: ["/company"],
    "/team": lambda w: ["/team"],
    "/auth/magic/{token}": lambda w: [f"/auth/magic/{w['magic_token']}"],
}

#: Достижимые из модели значения статусов, которых сторож не ждёт, — с причиной. Всё остальное из enum контракта
#: обязано встретиться в ответах.
UNREACHABLE = {
    "/deliveries": {"ready_to_ship": "у Fulfillment нет такого состояния; строки поставки по складу — M4"},
    "/documents": {
        "quote": "КП в /documents отдаёт FIX-23 (сейчас их нет среди GeneratedDocument)",
        "specification": "вида «спецификация» среди шаблонов документов нет",
        "waybill": "вида «накладная» среди шаблонов документов нет",
        "receipt": "вида «квитанция» среди шаблонов документов нет",
    },
}

#: Путь списка → (путь внутри элемента, имя enum в компонентах контракта).
STATUS_FIELDS = {
    "/requests": ("status", "RequestStatus"),
    "/quotes": ("status", "QuoteStatus"),
    "/contracts": ("status", "ContractStatus"),
    "/invoices": ("status", "InvoiceStatus"),
    "/acts": ("status", "ActStatus"),
    "/deliveries": ("status", "DeliveryStatus"),
    "/documents": ("kind", "DocumentKind"),
}


def _distinct(problems: list[str]) -> list[str]:
    """Одинаковые нарушения у разных элементов списка и разных id — одной строкой (читаемый отчёт сторожа)."""
    seen: dict[str, str] = {}
    for problem in problems:
        seen.setdefault(re.sub(r"\[\d+\]|/\d+| \d+:", "[]", problem), problem)
    return list(seen.values())


def api(path: str) -> str:
    return PREFIX + path


def anonymous_for(path: str) -> bool:
    return path.startswith("/auth/")


def fetch(client, anon_client, contract_path: str, url: str):
    return (anon_client if anonymous_for(contract_path) else client).get(api(url))


# ── 0. Контракт на месте и охват ───────────────────────────────────────────────────────────────────


def test_contract_is_mounted_and_readable():
    path = find_contract_path()
    assert path.name == "erp-portal.yaml"
    assert load_contract()["info"]["version"] == "0.2.0"


def test_every_contract_get_is_covered_by_the_guard():
    missing = contract_get_paths() - set(GET_CASES)
    stale = set(GET_CASES) - contract_get_paths()
    assert not missing, f"GET-эндпоинты контракта без фикстур сторожа: {sorted(missing)}"
    assert not stale, f"строки сторожа без GET в контракте: {sorted(stale)}"


def _portal_get_routes() -> set[str]:
    routes: set[str] = set()

    def walk(patterns, prefix=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                view = getattr(pattern.callback, "view_class", None)
                if view is not None and hasattr(view, "get"):
                    routes.add(prefix + str(pattern.pattern))

    walk(get_resolver().url_patterns)
    portal = set()
    for route in routes:
        if not route.startswith("api/portal/v1/"):
            continue
        path = "/" + route.removeprefix("api/portal/v1/")
        path = path.replace("<int:pk>", "{id}").replace("<str:token>", "{token}").rstrip("/") or "/"
        portal.add(path)
    return portal


def test_every_portal_get_route_is_in_the_contract():
    """Обратная сторона: маршрут GET, которого нет в контракте, — это недокументированный эндпоинт."""
    extra = _portal_get_routes() - contract_get_paths()
    assert not extra, f"GET-маршруты портала, которых нет в erp-portal.yaml: {sorted(extra)}"


# ── 1. Ответы по схемам ─────────────────────────────────────────────────────────────────────────────

JSON_GET_PATHS = sorted(set(GET_CASES) - {"/documents/{id}/file"})


@pytest.mark.parametrize("contract_path", JSON_GET_PATHS)
def test_get_responses_match_contract_schema(contract_path, contract_world, portal_client, anon_portal_client):
    schema = response_schema(contract_path, "get")
    urls = GET_CASES[contract_path](contract_world)
    assert urls, f"{contract_path}: нет URL для опроса"
    problems: list[str] = []
    for url in urls:
        response = fetch(portal_client, anon_portal_client, contract_path, url)
        assert response.status_code == 200, f"GET {url} → {response.status_code} {response.content[:300]!r}"
        body = response.json()
        if isinstance(body, list):
            assert body, f"GET {url}: пустой список — фикстуры не покрывают эндпоинт"
        problems += [f"GET {url} {problem}" for problem in check_response(body, schema)]
    assert not problems, "Ответ портала расходится с erp-portal.yaml:\n" + "\n".join(_distinct(problems))


@pytest.mark.parametrize("contract_path", sorted(STATUS_FIELDS))
def test_every_reachable_enum_value_is_exercised(contract_path, contract_world, portal_client):
    field, enum_name = STATUS_FIELDS[contract_path]
    expected = set(component(enum_name)["enum"]) - set(UNREACHABLE.get(contract_path, {}))
    seen = {item[field] for item in portal_client.get(api(contract_path)).json()}
    assert seen == expected, (
        f"{contract_path}.{field}: в ответах {sorted(seen)}, контракт требует {sorted(expected)} "
        f"(недостижимые с причиной — UNREACHABLE)"
    )


def test_documents_file_endpoint(contract_world, portal_client):
    ready = contract_world["documents"]["contract"]
    response = portal_client.get(api(f"/documents/{ready.pk}/file"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/pdf")
    pending = contract_world["documents"]["pending"]  # PDF ещё не отрисован
    response = portal_client.get(api(f"/documents/{pending.pk}/file"))
    assert response.status_code == 202
    assert response["Retry-After"].isdigit()
    assert response.json()["detail"] in error_codes()


def test_ids_referenced_by_documents_exist_in_documents_list(contract_world, portal_client):
    """document_id / pdf_document_id / scan_document_id ведут на настоящий документ из GET /documents (или null)."""
    known = {item["id"] for item in portal_client.get(api("/documents")).json()}
    referenced: list[tuple[str, int]] = []
    for path, keys in (
        ("/contracts", ("document_id",)),
        ("/invoices", ("document_id",)),
        ("/acts", ("document_id", "scan_document_id")),
        ("/quotes", ()),
    ):
        for item in portal_client.get(api(path)).json():
            referenced += [(f"{path}#{item['id']}.{key}", item[key]) for key in keys if item.get(key) is not None]
    for quote in portal_client.get(api("/quotes")).json():
        detail = portal_client.get(api(f"/quotes/{quote['id']}")).json()
        if detail.get("pdf_document_id") is not None:
            referenced.append((f"/quotes#{quote['id']}.pdf_document_id", detail["pdf_document_id"]))
    dangling = [(where, doc_id) for where, doc_id in referenced if doc_id not in known]
    assert not dangling, f"ссылки на несуществующие документы: {dangling}"


# ── 2. Тела ошибок ──────────────────────────────────────────────────────────────────────────────────


def _error_cases(world):
    """(описание, функция запроса, ожидаемый статус, ожидаемый код)."""
    quote = world["quotes"]["sent"]
    finalized = world["quotes"]["accepted"]
    contract = world["contracts"]["signed"]
    act = world["acts"]["accepted"]
    other_quote = world["other"]["quote"]
    return [
        ("нет сессии", "anon", lambda c: c.get(api("/me")), 401, "UNAUTHORIZED"),
        ("чужая компания", "user", lambda c: c.get(api(f"/quotes/{other_quote.pk}")), 404, "NOT_FOUND"),
        ("чужой запрос", "user", lambda c: c.get(api(f"/requests/{world['other']['deal'].pk}")), 404, "NOT_FOUND"),
        (
            "нет права действовать",
            "readonly",
            lambda c: c.post(api(f"/quotes/{quote.pk}/reject"), {"reason": "x"}, format="json"),
            403,
            "FORBIDDEN",
        ),
        (
            "пустая причина",
            "user",
            lambda c: c.post(api(f"/quotes/{quote.pk}/reject"), {"reason": "  "}, format="json"),
            422,
            "REASON_REQUIRED",
        ),
        (
            "КП уже принято",
            "user",
            lambda c: c.post(api(f"/quotes/{finalized.pk}/reject"), {"reason": "поздно"}, format="json"),
            409,
            "QUOTE_FINALIZED",
        ),
        (
            "неверный код акцепта",
            "user",
            lambda c: c.post(api(f"/quotes/{quote.pk}/accept"), {"code": "000000"}, format="json"),
            409,
            "QUOTE_CODE_INVALID",
        ),
        (
            "договор уже подписан",
            "user",
            lambda c: c.post(api(f"/contracts/{contract.pk}/sign"), format="json"),
            409,
            "CONTRACT_FINALIZED",
        ),
        (
            "акт уже принят",
            "user",
            lambda c: c.post(api(f"/acts/{act.pk}/accept"), format="json"),
            409,
            "ACT_FINALIZED",
        ),
        (
            "ссылка просрочена",
            "anon",
            lambda c: c.post(api("/auth/magic"), {"token": "x" * 32}, format="json"),
            410,
            "MAGIC_LINK_EXPIRED",
        ),
        (
            "ссылка просрочена (GET)",
            "anon",
            lambda c: c.get(api("/auth/magic/unknown-token")),
            410,
            "MAGIC_LINK_EXPIRED",
        ),
        (
            "плохое тело запроса",
            "user",
            lambda c: c.post(api("/requests"), {"lines": []}, format="json"),
            422,
            "VALIDATION_ERROR",
        ),
        ("плохой ИНН", "user", lambda c: c.put(api("/company"), {"inn": "123"}, format="json"), 422, "INN_INVALID"),
        (
            "битый JSON",
            "user",
            lambda c: c.post(api("/requests"), "{not json", content_type="application/json"),
            422,
            "VALIDATION_ERROR",
        ),
        (
            "не JSON",
            "user",
            lambda c: c.post(api("/requests"), "a=b", content_type="text/plain"),
            415,
            "UNSUPPORTED_MEDIA_TYPE",
        ),
        ("нет файла", "user", lambda c: c.post(api("/uploads"), {}, format="multipart"), 400, "FILE_REQUIRED"),
    ]


def _client_for(kind, portal_client, readonly_portal_client, anon_portal_client):
    return {"user": portal_client, "readonly": readonly_portal_client, "anon": anon_portal_client}[kind]


def test_error_bodies_are_error_schema_with_known_codes(
    contract_world, portal_client, readonly_portal_client, anon_portal_client
):
    error_schema = component("Error")
    codes = set(error_codes())
    problems = []
    for title, kind, call, status_code, code in _error_cases(contract_world):
        client = _client_for(kind, portal_client, readonly_portal_client, anon_portal_client)
        response = call(client)
        body = response.json()
        if response.status_code != status_code or body.get("detail") != code:
            problems.append(f"{title}: ждали {status_code} {code}, получили {response.status_code} {body}")
            continue
        problems += [f"{title}: {m}" for m in schema_errors(body, error_schema)]
        problems += [f"{title}: лишний ключ {k!r}" for k in body if k != "detail"]
        if body["detail"] not in codes:
            problems.append(f"{title}: detail {body['detail']!r} нет в ErrorCode")
    assert not problems, "\n".join(problems)


def test_missing_idempotency_key_is_400_with_known_code(contract_world, portal_client):
    client = PortalAPIClient()
    client.cookies.update(portal_client.cookies)
    client.credentials(**portal_client._credentials)
    client.auto_idempotency_key = False
    response = client.post(api("/requests"), {"summary": "x", "lines": []}, format="json")
    assert response.status_code == 400
    assert response.json() == {"detail": "IDEMPOTENCY_KEY_REQUIRED"}
    assert "IDEMPOTENCY_KEY_REQUIRED" in error_codes()


def test_magic_token_constant_is_not_a_secret():
    """Токен фикстур — явная заглушка, не рабочий секрет."""
    assert MAGIC_TOKEN.startswith("magic-token-for-contract-guard")
