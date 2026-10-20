"""Сторож контракта шва CRM → ERP (FIX-30, находки I-2, I-3): ответы integration проверяются по `erp-integration.yaml`.

Что проверяется для КАЖДОГО GET контракта на фикстуре «сделка с КП, договорами, счетами, оплатой, строками поставки
и актами во всех статусах» и на пустых сделках и клиентах:

1. ответ проходит JSON Schema из контракта (`$ref` раскрыты; типы, форматы, enum, `required`, `null`);
2. множество ключей любого объекта ⊆ `properties` схемы — контракт без `additionalProperties: false` не значит
   «можно лишнее» (так в ответы просачиваются внутренние поля);
3. каждое значение enum, достижимое из модели (`DealStage`, статусы КП, счёта, акта, поставки), встретилось в ответах —
   иначе статус «не проверен»;
4. тела ошибок — `{"detail": <код>}` по схеме `Error`.

Код проверок общий с сторожем портала (`core/tests/openapi_contract.py`). Падение сторожа — падение теста: ни `skip`,
ни `importorskip`; нет контракта на диске — падение с подсказкой про монтирование.
"""

from __future__ import annotations

import pytest
from integration.tests.contract_support import (
    PREFIX,
    check_response,
    component,
    contract_get_paths,
    enum_values,
    response_schema,
    schema_errors,
)
from integration.tests.world import build_integration_world
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

TOKEN = "test-service-token"  # conftest._seam_secrets


@pytest.fixture(autouse=True)
def _integration_env(settings):
    settings.CABINET_URL = "http://cabinet.localhost"
    settings.FRONTEND_URL = "http://erp.localhost"
    settings.ERP_VERSION = "0.2.0"


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
    "/documents/{erp_document_id}/link": lambda w: [f"/documents/{w['document'].pk}/link"],
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
