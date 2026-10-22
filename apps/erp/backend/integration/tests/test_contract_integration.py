"""Сторож контракта шва CRM → ERP (FIX-30, находки I-2, I-3): ответы integration проверяются по `erp-integration.yaml`.

Что проверяется для КАЖДОГО GET контракта на фикстуре «сделка с КП, договорами, счетами, оплатой, строками поставки
и актами во всех статусах» и на пустых сделках и клиентах:

1. ответ проходит JSON Schema из контракта (`$ref` раскрыты; типы, форматы, enum, `required`, `null`);
2. множество ключей любого объекта ⊆ `properties` схемы — контракт без `additionalProperties: false` не значит
   «можно лишнее» (так в ответы просачиваются внутренние поля);
3. каждое значение enum, достижимое из модели (`DealStage`, статусы КП, счёта, акта, поставки), встретилось в ответах —
   иначе статус «не проверен»;
4. тела ошибок — `{"detail": <код>}` по схеме `Error`.

FIX-35: сторож покрывает ВСЕ операции контракта — не только GET, но и `POST /clients/handoff`, `PUT /contacts/{id}`,
`POST /users/provision`, `DELETE /users/{id}/sessions`, и КАЖДЫЙ код ответа, который контракт обещает (200, 201, 204, 401,
404, 409, 422, 503): `test_every_documented_status_is_exercised` падает, если для операции или кода нет вызова.

FIX-60a (контракт 0.3.0): `Contact` и `ContactIn` закрыты через `unevaluatedProperties`, ответы проверяются по схеме
контракта как есть — без обхода `allOf`; на КАЖДУЮ из 13 операций (12 + выключатель внешнего сервиса, M3-ERP-06) есть вызов, дающий 429 `TOO_MANY_REQUESTS` с `Retry-After`
(лимит сервисного токена `INTEGRATION_RATE`, Q-FIX35-1).

Код проверок общий с сторожем портала (`core/tests/openapi_contract.py`). Падение сторожа — падение теста: ни `skip`,
ни `importorskip`; нет контракта на диске — падение с подсказкой про монтирование.
"""

from __future__ import annotations

import json
import uuid

import pytest
from integration.tests.contract_support import (
    PREFIX,
    check_response,
    component,
    contract_get_paths,
    contract_operations,
    enum_values,
    response_schema,
    schema_errors,
)
from integration.tests.world import build_integration_world
from portal.services.documents import encode_document_id
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

pytestmark = pytest.mark.django_db

TOKEN = "test-service-token"  # conftest._seam_secrets


@pytest.fixture(autouse=True)
def _integration_env(settings):
    settings.CABINET_URL = "http://cabinet.localhost"
    settings.FRONTEND_URL = "http://erp.localhost"
    settings.ERP_VERSION = "0.2.0"


@pytest.fixture(autouse=True)
def _no_anon_throttle(monkeypatch):
    """Запросов сторожа больше 20 в минуту: общий анонимный лимит (токен CRM — не пользователь) здесь не предмет проверки."""
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "100000/minute")


@pytest.fixture
def client():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
    return api


@pytest.fixture
def world():
    return build_integration_world()


@pytest.fixture
def catalog_product(db):
    from catalog.models import Category, Product, ProductStatus
    from core.models import Currency
    from master_data.models import UnitOfMeasure

    uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум"})
    unit, _ = UnitOfMeasure.objects.get_or_create(code="796", defaults={"name": "шт"})
    published, _ = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован"})
    return Product.objects.create(
        name="Рельс Р65 для сторожа",
        category=Category.objects.create(name="Рельсы"),
        uom=unit,
        status=published,
        list_price=12500000,
        list_price_currency=uzs,
        price_visibility="cabinet",
    )


def all_deals(world):
    return [world["full"], world["empty"], *world["stages"].values(), *(f.deal for f in world["deliveries"].values())]


def link_ids(world):
    """`erp_document_id` (id портала, FIX-38) документа каждого вида, который отдаёт integration."""
    return [
        encode_document_id("generated", world["document"].pk),
        encode_document_id("quote", world["sent_quote"].pk),
        encode_document_id("contract", world["contracts"]["signed"].pk),
        encode_document_id("invoice", world["invoices"]["paid"].pk),
        encode_document_id("act", world["acts"]["accepted"].pk),
        encode_document_id("waybill", world["fulfillment"].pk),
    ]


#: Какие URL опрашивает сторож по каждому GET-пути контракта. Новый GET в контракте без строки здесь роняет
#: `test_every_contract_get_is_covered`: новый эндпоинт нельзя добавить, не заведя для него фикстур.
GET_CASES = {
    "/companies/{erp_company_id}/summary": lambda w: [
        f"/companies/{w['company'].pk}/summary",
        f"/companies/{w['empty_company'].pk}/summary",
    ],
    "/companies/{erp_company_id}/deals": lambda w: [
        f"/companies/{w['company'].pk}/deals",
        f"/companies/{w['empty_company'].pk}/deals",
    ],
    "/deals/{erp_deal_id}": lambda w: [f"/deals/{deal.pk}" for deal in all_deals(w)],
    "/deals/{erp_deal_id}/documents": lambda w: [f"/deals/{deal.pk}/documents" for deal in all_deals(w)],
    "/documents/{erp_document_id}/link": lambda w: [f"/documents/{i}/link" for i in link_ids(w)],
    "/catalog/search": lambda w: ["/catalog/search?q=Рельс&mode=lead", "/catalog/search?q=Рельс&mode=client"],
    "/ai-usage": lambda w: ["/ai-usage?date_from=2026-01-01&date_to=2026-12-31"],
    "/health": lambda w: ["/health"],
}


def collect(client, world):
    """(путь контракта, URL, тело ответа) по всем опрашиваемым адресам."""
    out = []
    for path, urls in GET_CASES.items():
        for url in urls(world):
            response = client.get(PREFIX + url, HTTP_X_CRM_CONTEXT='{"crm_client_id": 7001, "channel": "crm"}')
            assert response.status_code == 200, f"GET {url}: {response.status_code} {response.content[:300]!r}"
            out.append((path, url, response.json()))
    return out


def test_every_contract_get_is_covered():
    assert contract_get_paths() == set(
        GET_CASES
    ), "в контракте появился или пропал GET — заведи для него фикстуры и строку в GET_CASES"


def test_every_get_response_matches_the_contract(client, world, catalog_product):
    problems = []
    for path, url, body in collect(client, world):
        problems += [f"GET {url}: {problem}" for problem in check_response(body, response_schema(path))]
    assert not problems, "\n".join(problems)


def test_health_externals_cover_every_contract_code_and_status_is_in_the_enum(client, world):
    """M3-ERP-06: `/health` несёт все шесть кодов контракта, статусы — из enum; сторож не проходит на пустом `externals`."""
    health = client.get(f"{PREFIX}/health").json()
    codes = [item["code"] for item in health["externals"]]
    assert sorted(codes) == sorted(enum_values("ExternalServiceCode")) and len(codes) == 6
    allowed = set(component("ExternalService")["properties"]["status"]["enum"])
    assert {item["status"] for item in health["externals"]} <= allowed
    assert not check_response(health, response_schema("/health"))


def test_deal_responses_are_not_empty_for_the_full_deal(client, world):
    """Сторож не должен проходить на пустых ответах: у полной сделки есть всё, что описывает контракт."""
    deal = client.get(f"{PREFIX}/deals/{world['full'].pk}").json()
    for key in ("quotes", "contracts", "invoices", "deliveries", "acts"):
        assert deal[key], f"в ответе по полной сделке пусто: {key}"
    assert deal["amount"] == "84000000.00"
    summary = client.get(f"{PREFIX}/companies/{world['company'].pk}/summary").json()
    assert summary["open_deals"] and summary["last_document"] and summary["next_delivery"]


def test_empty_deal_is_a_valid_deal(client, world):
    deal = client.get(f"{PREFIX}/deals/{world['empty'].pk}").json()
    assert not check_response(deal, response_schema("/deals/{erp_deal_id}"))
    assert deal["stage"] == "request"
    assert deal["amount"] is None and deal["currency"] == "UZS"
    assert deal["title"] == f"Сделка #{world['empty'].pk}"
    assert deal["quotes"] == deal["contracts"] == deal["invoices"] == deal["deliveries"] == deal["acts"] == []


def test_company_without_deals_is_a_valid_summary(client, world):
    summary = client.get(f"{PREFIX}/companies/{world['empty_company'].pk}/summary").json()
    assert not check_response(summary, response_schema("/companies/{erp_company_id}/summary"))
    assert summary["open_deals"] == []
    assert summary["last_document"] is None and summary["next_delivery"] is None
    assert summary["receivables"] == {"amount": "0.00", "currency": "UZS"}
    assert client.get(f"{PREFIX}/companies/{world['empty_company'].pk}/deals").json() == []


# ── Каждое значение enum, достижимое из модели, встретилось в ответах ─────────────────────────────────

#: Значения контракта, которые из модели пока не достижимы. Договор в черновике и аннулированный клиенту не показываются
#: (Q-FIX22-2): `contract_status` на них — ошибка вызова, не молчаливая подмена. `ready_to_ship` у исполнения сделки нет:
#: склад и отгрузка по строкам — M4, до того строка этот статус не получает.
UNREACHABLE = {"ContractStatus": {"draft", "cancelled"}, "DeliveryStatus": {"ready_to_ship"}}


def _walk(node, key):
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key and isinstance(value, str):
                yield value
            yield from _walk(value, key)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, key)


def test_every_reachable_status_value_appears_in_some_response(client, world, catalog_product):
    bodies = [body for path, _, body in collect(client, world) if path.startswith(("/deals/{erp_deal_id}", "/comp"))]
    deals = [body for path, url, body in collect(client, world) if path == "/deals/{erp_deal_id}"]
    seen_stages = set(_walk(bodies, "stage"))
    assert seen_stages == set(enum_values("DealStage")), "стадии контракта, не встретившиеся в ответах: " + ", ".join(
        sorted(set(enum_values("DealStage")) - seen_stages)
    )

    def statuses(collection):
        return {item["status"] for body in deals for item in body[collection]}

    expectations = {
        "QuoteStatus": statuses("quotes"),
        "ContractStatus": statuses("contracts"),
        "InvoiceStatus": statuses("invoices"),
        "DeliveryStatus": statuses("deliveries"),
        "ActStatus": statuses("acts"),
    }
    for schema_name, seen in expectations.items():
        reachable = set(enum_values(schema_name)) - UNREACHABLE.get(schema_name, set())
        assert (
            seen == reachable
        ), f"{schema_name}: не встретились {sorted(reachable - seen)}, лишние {sorted(seen - reachable)}"


# ── Ошибки и сам сторож ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "/companies/999999/summary",
        "/companies/999999/deals",
        "/deals/999999",
        "/deals/999999/documents",
        "/documents/999999/link",
    ],
)
def test_unknown_ids_answer_404_error_body(client, url):
    response = client.get(PREFIX + url)
    assert response.status_code == 404
    assert response.json() == {"detail": "NOT_FOUND"}
    assert not schema_errors(response.json(), component("Error"))


def test_request_without_token_is_401_with_error_body():
    response = APIClient().get(f"{PREFIX}/deals/1")
    assert response.status_code == 401
    assert not schema_errors(response.json(), component("Error"))


def test_guard_detects_broken_responses(client, world):
    """Сам сторож: подмена любого поля на не-контрактное значение — ненулевой список нарушений."""
    schema = response_schema("/deals/{erp_deal_id}")
    good = client.get(f"{PREFIX}/deals/{world['full'].pk}").json()
    assert check_response(good, schema) == []

    def broken(**changes):
        body = {**good, **changes}
        return check_response(body, schema)

    assert broken(stage="quoted"), "стадия не из контракта"
    assert broken(stage="CLOSED_WON"), "сырой код FSM"
    assert broken(amount=84000000.0), "сумма числом, а не строкой с двумя знаками"
    assert broken(amount="84000000"), "сумма без копеек"
    assert broken(currency="uzs")
    assert broken(internal_margin="12.5"), "лишний ключ"
    assert broken(quotes=[{**good["quotes"][0], "cost": "1.00"}]), "лишний ключ внутри КП"
    assert broken(invoices=[{**good["invoices"][0], "status": "PAID"}]), "статус счёта не из контракта"
    assert broken(contracts=[{**good["contracts"][0], "status": "PENDING_CLIENT"}])
    assert broken(updated_at="2026-10-20"), "дата без времени и часового пояса"
    bad_delivery = {**good["deliveries"][0], "status": "PENDING"}
    assert broken(deliveries=[bad_delivery])
    missing = dict(good)
    del missing["acts"]
    assert check_response(missing, schema)


# ── Все операции контракта и все обещанные коды ответов (FIX-35, I-15, G-5) ────────────────────────────

WRITE_PATHS = {
    ("POST", "/clients/handoff"),
    ("PUT", "/contacts/{crm_contact_id}"),
    ("POST", "/users/provision"),
    ("DELETE", "/users/{crm_user_id}/sessions"),
    ("POST", "/pairing/accept"),
    ("POST", "/pairing/rotate"),
    ("PUT", "/externals/{code}/switch"),
}


def handoff_body(crm_client_id, inn):
    return {
        "crm_client_id": crm_client_id,
        "crm_lead_id": 501,
        "company": {"name": "ООО Сторож Передачи", "inn": inn, "segment": "enterprise", "language": "ru"},
        "contacts": [
            {
                "crm_contact_id": crm_client_id * 10 + 1,
                "name": "Иван Иванов",
                "phone": "+998901234567",
                "email": f"guard{crm_client_id}@client.uz",
                "telegram_user_id": 12345678,
                "language": "ru",
                "is_primary": True,
                "preferred_channel": "both",
            }
        ],
        "need": {"summary": "Поставка рельсов Р65, 500 тонн", "product_interest": ["Рельс Р65"], "attachments": []},
        "owner": {"crm_user_id": 101, "name": "Менеджер Продаж"},
        "consent": {"given_at": "2026-10-01T09:30:00+05:00", "version": "2026-09"},
        "create_request": True,
        "invite": {"channels": ["email"]},
    }


def provision_body(crm_user_id, email):
    return {
        "crm_user_id": crm_user_id,
        "email": email,
        "name": "Сотрудник Сторожа",
        "role": "backoffice",
        "permissions": ["deal.manage"],
        "role_codes": ["CALCULATION"],
        "is_active": True,
    }


PAIRING_SECRETS = {
    "crm_to_erp_token": "guard-crm-to-erp-" + "a" * 32,
    "erp_to_crm_token": "guard-erp-to-crm-" + "b" * 32,
    "webhook_secret": "guard-webhook-secret-" + "c" * 32,
}
ROTATED_SECRETS = {
    "crm_to_erp_token": "guard-rotated-crm-to-erp-" + "d" * 32,
    "erp_to_crm_token": "guard-rotated-erp-to-crm-" + "e" * 32,
    "webhook_secret": "guard-rotated-webhook-" + "f" * 32,
}


#: Вызов на каждую операцию контракта для проверки лимита: первый запрос берёт единственное разрешение `1/minute`
#: (ответ любой: 200/404/422 — не важно), второй обязан получить 429. Ключ — (МЕТОД, путь контракта).
THROTTLE_CASES = {
    ("GET", "/companies/{erp_company_id}/summary"): ("/companies/999999/summary", None),
    ("GET", "/companies/{erp_company_id}/deals"): ("/companies/999999/deals", None),
    ("GET", "/deals/{erp_deal_id}"): ("/deals/999999", None),
    ("GET", "/deals/{erp_deal_id}/documents"): ("/deals/999999/documents", None),
    ("GET", "/documents/{erp_document_id}/link"): ("/documents/999999/link", None),
    ("GET", "/catalog/search"): ("/catalog/search?q=рельс&mode=lead", None),
    ("GET", "/ai-usage"): ("/ai-usage?date_from=2026-01-01&date_to=2026-12-31", None),
    ("GET", "/health"): ("/health", None),
    ("POST", "/clients/handoff"): ("/clients/handoff", handoff_body(8301, "830100001")),
    ("PUT", "/contacts/{crm_contact_id}"): ("/contacts/999999", handoff_body(8301, "830100001")["contacts"][0]),
    ("POST", "/users/provision"): ("/users/provision", provision_body(8901, "guard-8901@railtech.uz")),
    ("DELETE", "/users/{crm_user_id}/sessions"): ("/users/999999/sessions", None),
    # Сопряжение (M3-ERP-05): `accept` лимитирует свой scope `pairing` (по адресу), `rotate` — общий `integration`.
    ("POST", "/pairing/accept"): ("/pairing/accept", PAIRING_SECRETS),
    ("POST", "/pairing/rotate"): ("/pairing/rotate", ROTATED_SECRETS),
    ("PUT", "/externals/{code}/switch"): ("/externals/mail/switch", {"enabled": True}),
}


def hit_twice_with_one_per_minute(client, method, url, body, monkeypatch):
    """Два вызова операции при `INTEGRATION_RATE=1/minute`: (ответ первого, ответ второго)."""
    from django.core.cache import cache

    cache.clear()
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "integration", "1/minute")
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "pairing", "1/minute")
    responses = []
    for _ in range(2):
        kwargs = {"format": "json"} if body is not None else {}
        if method == "POST":
            kwargs["HTTP_IDEMPOTENCY_KEY"] = str(uuid.uuid4())  # у каждого вызова свой ключ: повтор не «тот же запрос»
        responses.append(
            getattr(client, method.lower())(PREFIX + url, **({"data": body} if body is not None else {}), **kwargs)
        )
    return responses


def exercise_all(client, world):
    """Вызывает каждую операцию контракта на каждый обещанный код ответа: [(МЕТОД, путь контракта, код, тело или None)]."""
    from django.core.cache import cache  # noqa: F401  (кэш чистит conftest перед тестом)
    from parties.models import CompanyType

    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})
    anonymous = APIClient()
    out = []

    def hit(method, path, url, expected, *, api=None, body=None, key=True):
        api = api or client
        kwargs = {"format": "json"} if body is not None else {}
        if key and method == "POST":
            kwargs["HTTP_IDEMPOTENCY_KEY"] = str(uuid.uuid4())
        response = getattr(api, method.lower())(PREFIX + url, **({"data": body} if body is not None else {}), **kwargs)
        assert response.status_code == expected, f"{method} {url}: {response.status_code} {response.content[:300]!r}"
        data = json.loads(response.content) if response.content else None
        out.append((method, path, response.status_code, data))
        return data

    # GET: 200 (все фикстуры), 404 (неизвестный id), 401 (без токена), 422 (каталог без запроса), 503 (здоровье)
    for path, url, body in collect(client, world):
        out.append(("GET", path, 200, body))
    unknown = {
        "/companies/{erp_company_id}/summary": "/companies/999999/summary",
        "/companies/{erp_company_id}/deals": "/companies/999999/deals",
        "/deals/{erp_deal_id}": "/deals/999999",
        "/deals/{erp_deal_id}/documents": "/deals/999999/documents",
        "/documents/{erp_document_id}/link": "/documents/999999/link",
    }
    for path, url in unknown.items():
        hit("GET", path, url, 404)
    for path, urls in GET_CASES.items():
        hit("GET", path, urls(world)[0], 401, api=anonymous)
    hit("GET", "/catalog/search", "/catalog/search?q=&mode=nonsense", 422)

    # POST /clients/handoff: 201 → 200 (повтор) → 409 (ИНН другого клиента) → 422 → 401
    created = hit("POST", "/clients/handoff", "/clients/handoff", 201, body=handoff_body(8101, "810100001"))
    hit("POST", "/clients/handoff", "/clients/handoff", 200, body=handoff_body(8101, "810100001"))
    hit("POST", "/clients/handoff", "/clients/handoff", 409, body=handoff_body(8102, "810100001"))
    hit("POST", "/clients/handoff", "/clients/handoff", 422, body={"crm_client_id": 1})
    hit("POST", "/clients/handoff", "/clients/handoff", 401, api=anonymous, body=handoff_body(8103, "810300001"))
    assert created["erp_company_id"]

    # PUT /contacts/{id}: 200 (контакт из передачи) → 404 → 422 → 401
    contact = handoff_body(8101, "810100001")["contacts"][0]
    contact_path = "/contacts/{crm_contact_id}"
    hit("PUT", contact_path, f"/contacts/{contact['crm_contact_id']}", 200, body={**contact, "name": "Пётр Петров"})
    hit("PUT", contact_path, "/contacts/999999", 404, body=contact)
    hit("PUT", contact_path, f"/contacts/{contact['crm_contact_id']}", 422, body={"name": "без обязательных полей"})
    hit("PUT", contact_path, f"/contacts/{contact['crm_contact_id']}", 401, api=anonymous, body=contact)

    # POST /users/provision: 201 → 200 → 409 (e-mail чужого crm_user_id) → 422 → 401
    provision = "/users/provision"
    hit("POST", provision, provision, 201, body=provision_body(8801, "guard-8801@railtech.uz"))
    hit("POST", provision, provision, 200, body=provision_body(8801, "guard-8801@railtech.uz"))
    hit("POST", provision, provision, 409, body=provision_body(8802, "guard-8801@railtech.uz"))
    hit("POST", provision, provision, 422, body={"crm_user_id": 8803})
    # FIX-63: чужой код системной роли — 422 (`role_codes`: SystemRoleCode)
    hit(
        "POST",
        provision,
        provision,
        422,
        body={**provision_body(8805, "guard-8805@railtech.uz"), "role_codes": ["ROOT"]},
    )
    hit("POST", provision, provision, 401, api=anonymous, body=provision_body(8804, "guard-8804@railtech.uz"))

    # DELETE /users/{id}/sessions: 204 → 404 → 401
    sessions = "/users/{crm_user_id}/sessions"
    hit("DELETE", sessions, "/users/8801/sessions", 204)
    hit("DELETE", sessions, "/users/999999/sessions", 404)
    hit("DELETE", sessions, "/users/8801/sessions", 401, api=anonymous)

    # PUT /externals/{code}/switch (M3-ERP-06): 200 → 404 (чужой код) → 409 (Sentry) → 422 → 401
    switch = "/externals/{code}/switch"
    state = hit("PUT", switch, "/externals/mail/switch", 200, body={"enabled": False, "reason": "сторож контракта"})
    assert state["enabled"] is False
    hit("PUT", switch, "/externals/mail/switch", 200, body={"enabled": True})
    hit("PUT", switch, "/externals/telegram/switch", 404, body={"enabled": False})
    hit("PUT", switch, "/externals/sentry/switch", 409, body={"enabled": False})
    hit("PUT", switch, "/externals/mail/switch", 422, body={"reason": "без enabled"})
    hit("PUT", switch, "/externals/mail/switch", 401, api=anonymous, body={"enabled": False})

    exercise_pairing(hit, anonymous, out)
    return out


def exercise_pairing(hit, anonymous, out):
    """Сопряжение (M3-ERP-05): `POST /pairing/accept` и `/pairing/rotate` на каждый обещанный код — в самом конце.

    После приёма токены лежат в БД и токен из `.env` перестаёт действовать, поэтому блок последний и в конце
    возвращает ERP к `.env` (иначе следующие вызовы фикстуры получили бы 401).
    """
    from integration.models import ServiceCredential
    from integration.services import pairing

    def with_token(token):
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return api

    accept, rotate = "/pairing/accept", "/pairing/rotate"
    rates = SimpleRateThrottle.THROTTLE_RATES
    saved_rates = dict(rates)
    try:
        # Первое сопряжение без кода (`X-Pairing-Proof`): 401 (подделка) → 200; после него — 409 (окно закрыто).
        import time as _time

        from django.conf import settings as django_settings
        from integration.services import bootstrap as bootstrap_proof

        def bootstrap_call(expected, *, secret=None):
            body = json.dumps(PAIRING_SECRETS, separators=(",", ":")).encode()
            header = bootstrap_proof.sign(
                secret or django_settings.PLATFORM_SSO_SECRET[0], body, int(_time.time()), uuid.uuid4().hex
            )
            response = APIClient().post(
                PREFIX + accept, data=body, content_type="application/json", HTTP_X_PAIRING_PROOF=header
            )
            assert response.status_code == expected, f"bootstrap: {response.status_code} {response.content[:200]!r}"
            out.append(("POST", accept, response.status_code, json.loads(response.content)))

        bootstrap_call(401, secret="not-the-shared-secret")
        bootstrap_call(200)
        bootstrap_call(409)

        code = pairing.issue_code().code
        hit("POST", accept, accept, 422, api=with_token(code), body={"crm_to_erp_token": "short"}, key=False)
        hit("POST", accept, accept, 200, api=with_token(code), body=PAIRING_SECRETS, key=False)
        hit("POST", accept, accept, 401, api=with_token(code), body=PAIRING_SECRETS, key=False)
        rates["pairing"] = "1/hour"
        hit("POST", accept, accept, 429, api=with_token(code), body=PAIRING_SECRETS, key=False)
        rates["pairing"] = saved_rates["pairing"]

        current = with_token(PAIRING_SECRETS["crm_to_erp_token"])
        hit("POST", rotate, rotate, 401, api=anonymous, body=ROTATED_SECRETS, key=False)
        hit("POST", rotate, rotate, 422, api=current, body={"webhook_secret": "short"}, key=False)
        hit("POST", rotate, rotate, 200, api=current, body=ROTATED_SECRETS, key=False)
        # 0.6.1: тройка, частично совпавшая с действующей (токен ERP→CRM тот же), — 422 PAIRING_PARTIAL_REPEAT.
        partial = {**ROTATED_SECRETS, "crm_to_erp_token": "guard-rotated-again-" + "g" * 32}
        hit("POST", rotate, rotate, 422, api=current, body=partial, key=False)
        rates["integration"] = "1/minute"
        hit("POST", rotate, rotate, 429, api=current, body=ROTATED_SECRETS, key=False)  # прежний токен ещё действует
    finally:
        rates.update(saved_rates)
        ServiceCredential.objects.all().delete()


@pytest.fixture
def exercised(client, world, catalog_product, monkeypatch):
    results = exercise_all(client, world)
    # 503: ERP деградировала — миграции не применены
    from django.db.migrations.executor import MigrationExecutor

    with monkeypatch.context() as degraded:
        degraded.setattr(MigrationExecutor, "migration_plan", lambda self, targets, clean_start=False: [("x", False)])
        response = client.get(f"{PREFIX}/health")
    assert response.status_code == 503, response.content
    results.append(("GET", "/health", 503, response.json()))
    # 429: лимит сервисного токена на каждой операции (FIX-60a, Q-FIX35-1)
    for (method, path), (url, body) in THROTTLE_CASES.items():
        _, limited = hit_twice_with_one_per_minute(client, method, url, body, monkeypatch)
        assert limited.status_code == 429, f"{method} {url}: {limited.status_code} {limited.content[:300]!r}"
        results.append((method, path, 429, limited.json()))
    return results


def test_every_operation_has_a_throttle_case():
    assert set(THROTTLE_CASES) == set(contract_operations()), "каждой операции контракта нужен вызов на 429"
    assert len(THROTTLE_CASES) == 15


@pytest.mark.parametrize(("method", "path"), sorted(THROTTLE_CASES), ids=lambda value: str(value))
def test_every_operation_answers_429_with_retry_after_over_the_limit(client, monkeypatch, method, path):
    """Q-FIX35-1: `INTEGRATION_RATE=1/minute` — второй вызов любой операции: 429 `TOO_MANY_REQUESTS` и `Retry-After`."""
    url, body = THROTTLE_CASES[(method, path)]
    first, limited = hit_twice_with_one_per_minute(client, method, url, body, monkeypatch)
    assert first.status_code != 429, f"{method} {url}: первый вызов уже ограничен"
    assert limited.status_code == 429, f"{method} {url}: {limited.status_code} {limited.content[:300]!r}"
    assert limited.json() == {"detail": "TOO_MANY_REQUESTS"}
    assert not schema_errors(limited.json(), component("Error"))
    assert int(limited["Retry-After"]) >= 1, "Retry-After — целое число секунд, не меньше 1 (контракт)"
    assert "429" in contract_operations()[(method, path)], "контракт обещает 429 на этой операции"


def test_operations_are_the_known_set():
    operations = set(contract_operations())
    assert (
        operations == {("GET", path) for path in GET_CASES} | WRITE_PATHS
    ), "в контракте появилась или пропала операция — заведи для неё вызовы в exercise_all и строку в WRITE_PATHS/GET_CASES"


def test_every_documented_status_is_exercised(exercised):
    documented = {
        (method, path, int(code)) for (method, path), codes in contract_operations().items() for code in codes
    }
    seen = {(method, path, status) for method, path, status, _ in exercised}
    assert documented - seen == set(), "контракт обещает коды, для которых нет вызова: " + ", ".join(
        f"{m} {p} → {c}" for m, p, c in sorted(documented - seen)
    )
    assert seen - documented == set(), "в ответах встретились коды, которых контракт не обещает: " + ", ".join(
        f"{m} {p} → {c}" for m, p, c in sorted(seen - documented)
    )


def test_every_response_of_every_operation_matches_the_contract(exercised):
    """Тело ответа любой операции на любой обещанный код проходит схему: 2xx/503 — своя схема, ошибки — `Error`."""
    problems = []
    for method, path, status, body in exercised:
        if status == 204:
            assert not body, f"{method} {path}: 204 с телом {body!r}"
            continue
        if status in (200, 201, 503):
            schema = response_schema(path, method.lower(), str(status))
        else:
            schema = component("Error")
        problems += [f"{method} {path} → {status}: {p}" for p in check_response(body, schema)]
    assert not problems, "\n".join(problems)


def test_error_codes_are_the_documented_ones(exercised):
    codes = {
        (status): {body["detail"] for _, _, st, body in exercised if st == status} for status in (401, 404, 409, 422)
    }
    assert (
        {"UNAUTHORIZED"}
        <= codes[401]
        <= {
            "UNAUTHORIZED",
            "PAIRING_CODE_INVALID",
            "PAIRING_CODE_EXPIRED",
            "PAIRING_CODE_USED",
            "PAIRING_PROOF_INVALID",
            "PAIRING_PROOF_EXPIRED",
            "PAIRING_PROOF_REPLAYED",
        }
    )
    assert codes[404] == {"NOT_FOUND"}
    assert codes[422] == {"VALIDATION_ERROR", "PAIRING_PARTIAL_REPEAT"}  # 0.6.1: частичный повтор ротации
    assert codes[409] <= {"INN_CONFLICT", "EMAIL_CONFLICT", "BOOTSTRAP_CLOSED", "NOT_SWITCHABLE"} and codes[409]


# --- FIX-63: `role_codes` в провижининге (SystemRoleCode) --------------------------------------------------------


def test_provision_request_serializer_fields_are_the_contract_properties():
    """Сторож тела: поля `ProvisionUserRequestSerializer` = свойства `ProvisionUserRequest` контракта (ни лишних, ни забытых)."""
    from integration.serializers import ProvisionUserRequestSerializer

    assert set(ProvisionUserRequestSerializer().fields) == set(component("ProvisionUserRequest")["properties"])


def test_role_codes_are_optional_in_the_contract_and_enum_equals_erp_catalog():
    from accounts.constants import BackofficeRoleCode

    request = component("ProvisionUserRequest")
    assert "role_codes" not in request["required"], "аддитивно: старый CRM поле не шлёт"
    assert request["properties"]["role_codes"]["items"] == component(
        "SystemRoleCode"
    ), "items — ссылка на SystemRoleCode"
    assert enum_values("SystemRoleCode") == list(BackofficeRoleCode.values)


def test_provision_with_every_system_role_code_of_the_contract(client, world, settings):
    from accounts.models import Company, CompanyMember, WorkspaceRole

    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 10})
    settings.OWN_COMPANY_ID = Company.objects.create(name="Own Co", inn="OWN-GUARD63").pk

    codes = enum_values("SystemRoleCode")
    response = client.post(
        f"{PREFIX}/users/provision",
        {**provision_body(8950, "guard-8950@railtech.uz"), "role_codes": codes},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert response.status_code == 201, response.content
    member = CompanyMember.objects.get(user__email="guard-8950@railtech.uz")
    assert set(member.company_roles.exclude(code="").values_list("code", flat=True)) == set(codes)
