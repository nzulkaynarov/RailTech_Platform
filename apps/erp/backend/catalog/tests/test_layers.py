"""M1-ERP-07 — два слоя каталога. DoD: внутренний слой не отдаётся ни одним публичным/клиентским эндпоинтом.

ORCHESTRATOR §3.5: клиент видит только опубликованный слой. Проверяется так:

1. **Перебор всех GET-эндпоинтов** из URLConf (тем же перечислителем, что строит OpenAPI) от имени
   анонима и покупательского аккаунта (клиент до M2-ERP-01): ни в одном ответе нет значений
   внутреннего слоя — имени поставщика, его артикула и цены, внутренней заметки, кода ТН ВЭД,
   скрытых фото и документов, черновика, цены карточки «по запросу». Проверяются ЗНАЧЕНИЯ, а не
   имена полей: так ловится и утечка через вложенные объекты, шаблоны и файлы.
2. **Контракт**: проекция `published_projection` отдаёт ровно поля `CatalogItem` из
   `packages/contracts/openapi/erp-portal.yaml` и проходит его JSON-схему.
3. **Негативные сценарии**: неопубликованная карточка клиенту не отдаётся, `on_request` — без цены,
   наличия и срока, услуга — без наличия; сотрудник без права себестоимости не видит поставщиков.
"""

import os
import re
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from django.utils import timezone
from drf_spectacular.generators import EndpointEnumerator
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import (
    Category,
    DomainType,
    Product,
    ProductDocument,
    ProductImage,
    ProductStatus,
    StockStatus,
    SupplierOffer,
)
from catalog.services.layers import (
    COMMERCIAL_FIELDS,
    INTERNAL_FIELDS,
    LEAD_FIELDS,
    PUBLISHED_FIELDS,
    client_line_reference,
    published_projection,
)
from master_data.models import Currency, UnitOfMeasure

pytestmark = pytest.mark.django_db

PRODUCTS_URL = "/api/v1/catalog/products/"

SECRET_SUPPLIER = "Поставщик-СЕКРЕТ-ZXQ"
SECRET_SUPPLIER_SKU = "SUPSKU-ZXQ-7781"
SECRET_COST = "987654.32"
SECRET_NOTE = "INTERNAL-NOTE-ZXQ"
SECRET_HS = "7777777777"
PRIVATE_IMAGE = "https://cdn.example/PRIVATE-IMG-ZXQ.png"
PRIVATE_DOC = "PRIVATE-DOC-ZXQ"
DRAFT_NAME = "DRAFT-CARD-ZXQ"
ON_REQUEST_PRICE = "555.55"
SENTINELS = (
    SECRET_SUPPLIER,
    SECRET_SUPPLIER_SKU,
    SECRET_COST,
    SECRET_NOTE,
    SECRET_HS,
    PRIVATE_IMAGE,
    PRIVATE_DOC,
    DRAFT_NAME,
    ON_REQUEST_PRICE,
)


@pytest.fixture
def world(db, grant):
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0]
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client"})[0]
    member_ws = WorkspaceRole.objects.get(code="MEMBER")
    owner_ws = WorkspaceRole.objects.get(code="OWNER")

    own = Company.objects.create(name="Своя компания L", inn="410000001")
    own.types.add(supplier_type)
    client_company = Company.objects.create(name="Клиент L", inn="410000002")
    client_company.types.add(client_type)
    secret_supplier = Company.objects.create(name=SECRET_SUPPLIER, inn="410000003")

    def member(company, email, workspace=member_ws):
        user = CustomUser.objects.create_user(email=email, username=email, password=None, is_active=True)
        CompanyMember.objects.create(user=user, company=company, role=workspace, is_primary=True, is_active=True)
        return user

    staff = member(own, "catalog@own.example")
    grant(staff, "CATALOG_SUPPLY")
    viewer = member(own, "viewer@own.example")
    grant(viewer, "VIEWER")
    buyer = member(client_company, "buyer@client.example", workspace=owner_ws)

    uzs = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "сум"})[0]
    goods = DomainType.objects.get(code=DomainType.GENERAL_GOODS)
    services = DomainType.objects.get(code=DomainType.SERVICES)
    pcs = UnitOfMeasure.objects.get(code="H87")
    hour = UnitOfMeasure.objects.get(code="HUR")
    published = ProductStatus.objects.get(code="PUBLISHED")
    category = Category.objects.filter(domain_type=goods).first()

    card = Product.objects.create(
        name="Насос центробежный L",
        description="Для чистой воды",
        specifications={"Мощность": "4 кВт", "Пусто": ""},
        domain_type=goods,
        category=category,
        uom=pcs,
        hs_code=SECRET_HS,
        owner_company=own,
        status=published,
        visibility="cabinet",
        list_price=Decimal("1500.00"),
        list_price_currency=uzs,
        client_lead_time_days=5,
        internal_notes=SECRET_NOTE,
        demand_count=17,
    )
    SupplierOffer.objects.create(
        product=card,
        supplier=secret_supplier,
        supplier_sku=SECRET_SUPPLIER_SKU,
        base_price=Decimal(SECRET_COST),
        currency=uzs,
        stock_status=StockStatus.objects.get(code="IN_STOCK"),
        stock_quantity=4,
    )
    ProductImage.objects.create(product=card, image_url="https://cdn.example/public.png", is_public=True)
    ProductImage.objects.create(product=card, image_url=PRIVATE_IMAGE, is_public=False)
    ProductDocument.objects.create(
        product=card, file_url="https://cdn.example/passport.pdf", name="Паспорт", is_public=True
    )
    ProductDocument.objects.create(product=card, file_url="https://cdn.example/x.pdf", name=PRIVATE_DOC)

    on_request = Product.objects.create(
        name="Задвижка по запросу L",
        description="Арматура",
        domain_type=goods,
        category=category,
        uom=pcs,
        owner_company=own,
        status=published,
        visibility="on_request",
        list_price=Decimal(ON_REQUEST_PRICE),
        list_price_currency=uzs,
        client_lead_time_days=9,
    )
    service = Product.objects.create(
        name="Пусконаладка L",
        description="Выезд инженера",
        domain_type=services,
        category=Category.objects.filter(domain_type=services).first(),
        uom=hour,
        fulfillment_policy="time",
        owner_company=own,
        status=published,
        visibility="cabinet",
        list_price=Decimal("250000.00"),
        list_price_currency=uzs,
    )
    draft = Product.objects.create(name=DRAFT_NAME, description="x", domain_type=goods, owner_company=own)
    return {
        "own": own,
        "client_company": client_company,
        "staff": staff,
        "viewer": viewer,
        "buyer": buyer,
        "card": card,
        "on_request": on_request,
        "service": service,
        "draft": draft,
        "uzs": uzs,
    }


@pytest.fixture
def sent_quote(world):
    """КП покупателю с позицией из каталога — чтобы перебор задел и сделку, и публичную страницу."""
    from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus

    stage = DealStage.objects.get_or_create(code="QUOTE_SENT", defaults={"name": "КП отправлено", "sort_order": 10})[0]
    status = QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено", "sort_order": 10})[0]
    deal = Deal.objects.create(company=world["client_company"], stage=stage, title="Сделка L")
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        number="КП-L-0001",
        status=status,
        seller_company=world["own"],
        prepared_by=world["staff"],
        quote_currency=world["uzs"],
        frozen_at=timezone.now(),
        public_access_token="layers-token-0001",
    )
    QuoteItem.objects.create(
        quote=quote,
        product=world["card"],
        quantity=2,
        frozen_base_price=Decimal("1000.00"),
        margin_percent=Decimal("20.00"),
        frozen_currency=world["uzs"],
    )
    return {"deal": deal, "quote": quote}


def _client(user=None):
    client = APIClient()
    client.raise_request_exception = False
    if user is not None:
        client.force_authenticate(user)
    return client


def _body(response) -> str:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content).decode("utf-8", "replace")
    return response.content.decode("utf-8", "replace")


def _get_paths():
    paths = {path for path, _regex, method, _cb in EndpointEnumerator().get_api_endpoints() if method == "GET"}
    return sorted(paths)


GET_PATHS = _get_paths()


def _urls(path, ids, token):
    params = re.findall(r"\{([^}]+)\}", path)
    if not params:
        return [path]
    urls = []
    for object_id in ids:
        url = path
        for name in params:
            if name == "token":
                value = token
            elif name in ("pk", "id") or name.endswith("_id"):
                value = str(object_id)
            else:
                value = "999999"
            url = url.replace("{" + name + "}", value)
        urls.append(url)
    return sorted(set(urls))


def _sweep(user, world, sent_quote) -> tuple[list[str], set[str]]:
    """Все GET-эндпоинты от имени `user`: (утечки «url: значение», url-ы, где видна сама карточка)."""
    ids = (world["card"].pk, world["draft"].pk, sent_quote["deal"].pk, sent_quote["quote"].pk)
    token = sent_quote["quote"].public_access_token
    client = _client(user)
    leaks, card_seen = [], set()
    for path in GET_PATHS:
        for url in _urls(path, ids, token):
            body = _body(client.get(url))
            leaks += [f"{url}: {secret}" for secret in SENTINELS if secret in body]
            if world["card"].name in body:
                card_seen.add(url)
    return leaks, card_seen


# ── 1. DoD: ни один публичный/клиентский эндпоинт не отдаёт внутренний слой ─────────────────


def test_inventory_covers_catalog_and_public_endpoints():
    assert len(GET_PATHS) > 100
    assert PRODUCTS_URL in GET_PATHS and PRODUCTS_URL + "{pk}/" in GET_PATHS
    assert any(path.startswith("/api/v1/public/") for path in GET_PATHS)


def test_no_get_endpoint_leaks_the_internal_layer_to_an_anonymous_visitor(world, sent_quote):
    leaks, _seen = _sweep(None, world, sent_quote)

    assert leaks == []


def test_no_get_endpoint_leaks_the_internal_layer_to_a_client_account(world, sent_quote):
    leaks, seen = _sweep(world["buyer"], world, sent_quote)

    assert leaks == []
    # Перебор действительно дошёл до карточки: каталог (список и карточка) отдал её клиенту.
    assert {PRODUCTS_URL, f"{PRODUCTS_URL}{world['card'].pk}/"} <= seen, sorted(seen)


def test_public_quote_page_shows_the_line_but_not_the_internal_layer(world, sent_quote):
    token = sent_quote["quote"].public_access_token
    page = _client().get(f"/api/v1/public/quotes/{token}/", HTTP_ACCEPT="text/html")

    assert page.status_code == 200
    html = _body(page)
    assert world["card"].name in html
    assert [secret for secret in SENTINELS if secret in html] == []


def test_client_documents_reference_the_card_only_through_the_published_layer(world, sent_quote):
    """Контекст публичной страницы и PDF КП несёт ссылку на карточку, а не модель."""
    from crm.services.documents import public_quote_page_context

    context = public_quote_page_context(sent_quote["quote"])
    product_refs = [row["product"] for row in context["items"] if row.get("display_type") == "ITEM"]

    assert product_refs == [client_line_reference(world["card"])]
    assert set(product_refs[0]) == {"id", "name"}


# ── 2. Контракт портала: проекция = CatalogItem ─────────────────────────────────────────────


def _portal_spec() -> dict:
    root = os.environ.get("ERP_CONTRACTS_DIR") or Path(__file__).resolve().parents[5] / "packages" / "contracts"
    return yaml.safe_load((Path(root) / "openapi" / "erp-portal.yaml").read_text(encoding="utf-8"))


def test_projection_emits_exactly_the_portal_catalog_item_fields(world):
    schema = _portal_spec()["components"]["schemas"]["CatalogItem"]

    assert set(PUBLISHED_FIELDS) == set(schema["properties"]), "проекция и контракт портала разошлись"
    assert schema.get("additionalProperties") is False
    for card in (world["card"], world["on_request"], world["service"]):
        data = published_projection(card)
        assert set(data) == set(PUBLISHED_FIELDS)
        assert set(schema["required"]) <= set(data)
        assert not set(data) & INTERNAL_FIELDS


def test_projection_validates_against_the_portal_json_schema(world):
    from jsonschema import Draft202012Validator

    spec = _portal_spec()
    validator = Draft202012Validator({"$ref": "#/components/schemas/CatalogItem", "components": spec["components"]})
    for card in (world["card"], world["on_request"], world["service"]):
        errors = [error.message for error in validator.iter_errors(published_projection(card))]
        assert errors == [], (card.name, errors)


def test_lead_mode_has_no_commercial_fields(world):
    data = published_projection(world["card"], mode="lead")

    assert set(data) == set(LEAD_FIELDS)
    assert not set(data) & set(COMMERCIAL_FIELDS)


# ── 3. Негативные сценарии клиента ─────────────────────────────────────────────────────────


def test_client_gets_only_published_cards_and_only_the_published_layer(world):
    response = _client(world["buyer"]).get(PRODUCTS_URL)

    assert response.status_code == 200
    rows = response.json()["results"]
    names = {row["name"] for row in rows}
    assert names == {world["card"].name, world["on_request"].name, world["service"].name}
    for row in rows:
        assert set(row) == set(PUBLISHED_FIELDS)


def test_unpublished_and_archived_cards_are_not_returned_to_a_client(world):
    archived = Product.objects.create(
        name="Архивная L", owner_company=world["own"], status=ProductStatus.objects.get(code="ARCHIVED")
    )
    client = _client(world["buyer"])

    assert client.get(f"{PRODUCTS_URL}{world['draft'].pk}/").status_code == 404
    assert client.get(f"{PRODUCTS_URL}{archived.pk}/").status_code == 404
    assert client.get(PRODUCTS_URL, {"search": DRAFT_NAME}).json()["results"] == []


def test_anonymous_visitor_gets_no_catalog(world):
    assert _client().get(PRODUCTS_URL).status_code == 401
    assert _client().get(f"{PRODUCTS_URL}{world['card'].pk}/").status_code == 401
    assert _client().get("/api/v1/catalog/offers/").status_code == 401


def test_cabinet_card_carries_price_availability_and_lead_time(world):
    data = _client(world["buyer"]).get(f"{PRODUCTS_URL}{world['card'].pk}/").json()

    assert data["price"] == {"amount": "1500.00", "currency": "UZS"}
    assert data["availability"] == "in_stock"
    assert data["lead_time_days"] == 5
    assert data["images"] == ["https://cdn.example/public.png"]
    assert data["documents"] == [{"name": "Паспорт", "url": "https://cdn.example/passport.pdf"}]
    assert data["attributes"] == [{"name": "Мощность", "value": "4 кВт"}]


def test_on_request_card_has_no_price_availability_or_lead_time(world):
    data = _client(world["buyer"]).get(f"{PRODUCTS_URL}{world['on_request'].pk}/").json()

    assert data["price"] is None and data["availability"] is None and data["lead_time_days"] is None


def test_service_has_a_policy_and_no_availability(world):
    data = published_projection(world["service"])

    assert data["kind"] == "service"
    assert data["fulfillment_policy"] == "time"
    assert data["availability"] is None
    assert data["unit"] == "час"
    assert data["price"] == {"amount": "250000.00", "currency": "UZS"}


def test_client_cannot_sort_or_filter_by_the_internal_layer(world):
    """Порядок выдачи не должен выдавать спрос и наличие у поставщика."""
    response = _client(world["buyer"]).get(PRODUCTS_URL, {"ordering": "-demand_count", "stock_status": "OUT_OF_STOCK"})

    assert [row["name"] for row in response.json()["results"]] == sorted(
        [world["card"].name, world["on_request"].name, world["service"].name]
    )


# ── 4. Внутренний слой у сотрудников: по праву ─────────────────────────────────────────────


def test_staff_with_catalog_rights_sees_the_internal_layer(world):
    data = _client(world["staff"]).get(f"{PRODUCTS_URL}{world['card'].pk}/").json()

    assert data["internal_notes"] == SECRET_NOTE
    assert data["offers"][0]["supplier_sku"] == SECRET_SUPPLIER_SKU
    assert data["base_price"] == SECRET_COST
    assert data["client_preview"] == published_projection(world["card"])


def test_staff_without_cost_rights_does_not_see_supplier_cost(world):
    data = _client(world["viewer"]).get(f"{PRODUCTS_URL}{world['card'].pk}/").json()

    assert "offers" not in data and "base_price" not in data and "base_price_currency" not in data
    assert _client(world["viewer"]).get("/api/v1/catalog/offers/").json()["results"] == []
