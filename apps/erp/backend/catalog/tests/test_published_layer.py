"""M1-ERP-07 — каталог в два слоя: опубликованный слой, политика видимости цен, порог публикации.

Главный инвариант (ORCHESTRATOR §3.5, DoD задачи): внутренний слой карточки — поставщики,
закупочные цены, артикулы поставщиков, остатки количеством, спрос — НЕ отдаётся ни одним
публичным или клиентским эндпоинтом. Проверяется двумя способами:

1. проекция `catalog.published.project` собирается белым списком ключей контракта портала;
2. обход ВСЕХ маршрутов ERP анонимом и покупательским аккаунтом: ни в одном ответе нет
   «меток» внутреннего слоя (имя поставщика, его артикул, закупочная цена, остаток, спрос).
"""

import datetime
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from parties.models import CompanySettings
from rest_framework.test import APIClient
from rest_framework.views import APIView

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.completeness import completeness
from catalog.constants import MODE_CLIENT, MODE_LEAD, FulfillmentPolicy, PriceVisibility
from catalog.models import Category, DomainType, Product, ProductStatus, StockStatus, SupplierOffer
from catalog.published import CATALOG_ITEM_KEYS, CLIENT_ONLY_KEYS, availability, project, project_many
from master_data.models import Currency, UnitOfMeasure

pytestmark = pytest.mark.django_db

#: Метки внутреннего слоя — значения, которых не бывает в ответах случайно.
SUPPLIER_NAME = "ПоставщикСекрет-Q7"
SUPPLIER_SKU = "SUPSKU-SECRET-5531"
COST = Decimal("48213.77")
STOCK_QTY = 917317
DEMAND = 731957
SENTINELS = (SUPPLIER_NAME, SUPPLIER_SKU, "48213.77", "48213,77", "48 213", str(STOCK_QTY), str(DEMAND))

TODAY = datetime.date.today()
#: Ссылка публичного КП для обхода маршрутов — тестовое значение, не секрет.
SWEEP_QUOTE_LINK = "tok_M107_SWEEP"


@pytest.fixture
def world(db, grant):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован"), ("ARCHIVED", "Архив")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code, name in (("IN_STOCK", "В наличии"), ("ON_ORDER", "Под заказ"), ("EXPECTED", "Ожидается")):
        StockStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    goods, _ = DomainType.objects.get_or_create(
        code="GENERAL_GOODS", defaults={"name": "Товары", "sku_prefix": "GD", "sort_order": 10}
    )
    services, _ = DomainType.objects.get_or_create(
        code="SERVICES", defaults={"name": "Услуги", "sku_prefix": "SV", "sort_order": 20}
    )
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    owner_role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    usd, _ = Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар США", "symbol": "$"})
    unit = UnitOfMeasure.objects.filter(code="796").first() or UnitOfMeasure.objects.create(code="796", name="шт")
    category = Category.objects.create(name="Подшипники M107")

    own = Company.objects.create(name="ООО Своя Компания", inn="9810000001")
    own.types.add(supplier_type)
    staff = CustomUser.objects.create_user(email="m107.staff@test.uz", username="m107.staff@test.uz", password="pw")
    CompanyMember.objects.create(user=staff, company=own, role=owner_role, is_active=True, is_primary=True)
    grant(staff, "CATALOG_SUPPLY")

    # Поставщик — внутренний контрагент без сотрудников в ERP (не «своя компания»).
    supplier = Company.objects.create(name=SUPPLIER_NAME, inn="9810000002")
    supplier.types.add(supplier_type)

    client_company = Company.objects.create(name="ООО Клиент M107", inn="9810000003")
    buyer = CustomUser.objects.create_user(email="m107.buyer@test.uz", username="m107.buyer@test.uz", password="pw")
    CompanyMember.objects.create(user=buyer, company=client_company, role=owner_role, is_active=True, is_primary=True)

    staff_client = APIClient()
    staff_client.force_authenticate(staff)
    return {
        "goods": goods,
        "services": services,
        "usd": usd,
        "unit": unit,
        "category": category,
        "own": own,
        "supplier": supplier,
        "staff": staff,
        "staff_client": staff_client,
        "client_company": client_company,
        "buyer": buyer,
    }


def make_card(world, *, name="Подшипник 6205", published=True, service=False, offer=True, **fields):
    fields.setdefault("hs_code", "8482100000")
    product = Product.objects.create(
        name=name,
        description="Шариковый радиальный",
        owner_company=world["own"],
        domain_type=world["services"] if service else world["goods"],
        category=world["category"],
        uom=world["unit"],
        demand_count=DEMAND,
        specifications={"Диаметр": "52 мм", "Пустое": ""},
        status=ProductStatus.objects.get(code="PUBLISHED" if published else "DRAFT"),
        **fields,
    )
    if offer:
        SupplierOffer.objects.create(
            product=product,
            supplier=world["supplier"],
            supplier_sku=SUPPLIER_SKU,
            base_price=COST,
            currency=world["usd"],
            stock_quantity=STOCK_QTY,
            in_stock_lead_time_days=3,
            order_lead_time_days=21,
        )
    return product


def set_company_policy(world, **fields):
    CompanySettings.objects.update_or_create(company=world["own"], defaults=fields)


def assert_no_internal_layer(payload, where: str):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
    leaked = [sentinel for sentinel in SENTINELS if sentinel in text]
    assert not leaked, f"{where}: утечка внутреннего слоя {leaked}"


# ── 1. Проекция: белый список ключей ─────────────────────────────────────────────────────


def test_client_projection_is_whitelisted_and_carries_no_internal_layer(world):
    product = make_card(
        world, price_visibility=PriceVisibility.CABINET, list_price=Decimal("99.90"), list_price_currency=world["usd"]
    )

    item = project(product, mode=MODE_CLIENT)

    assert set(item) == CATALOG_ITEM_KEYS
    assert item["kind"] == "goods"
    assert item["unit"] == "шт"
    assert item["category"] == "Подшипники M107"
    assert item["attributes"] == [{"name": "Диаметр", "value": "52 мм"}], "пустые характеристики не публикуются"
    assert item["price"] == {"amount": "99.90", "currency": "USD"}
    assert item["availability"] == "in_stock" and item["lead_time_days"] == 3
    assert_no_internal_layer(item, "project(client)")


def test_lead_projection_has_no_price_availability_or_lead_time(world):
    product = make_card(
        world, price_visibility=PriceVisibility.CABINET, list_price=Decimal("99.90"), list_price_currency=world["usd"]
    )

    item = project(product, mode=MODE_LEAD)

    assert set(item) == CATALOG_ITEM_KEYS - CLIENT_ONLY_KEYS
    assert_no_internal_layer(item, "project(lead)")


def test_projection_rejects_unknown_mode(world):
    with pytest.raises(ValueError):
        project(make_card(world), mode="staff")


def test_projection_keys_match_portal_contract():
    """Ключи проекции = свойства `CatalogItem` в `packages/contracts` (контракт раньше кода).

    В контейнере тестов смонтирован только backend/ — тогда сверка пропускается, а в полном
    репозитории (make check-erp на хосте, локальный прогон) работает.
    """
    yaml = pytest.importorskip("yaml")
    candidates = (
        parent / "packages" / "contracts" / "openapi" / "erp-portal.yaml" for parent in Path(__file__).parents
    )
    contract = next((path for path in candidates if path.exists()), None)
    if contract is None:
        pytest.skip("packages/contracts не смонтирован")
    schema = yaml.safe_load(contract.read_text())["components"]["schemas"]["CatalogItem"]
    assert set(schema["properties"]) == CATALOG_ITEM_KEYS
    assert set(schema["required"]) <= CATALOG_ITEM_KEYS


# ── 2. Политика видимости цены ──────────────────────────────────────────────────────────


def _priced(world, **fields):
    return make_card(world, list_price=Decimal("1234.5"), list_price_currency=world["usd"], **fields)


def test_price_is_on_request_by_default(world):
    """BUSINESS §12: публикация цен по умолчанию — «по запросу»."""
    assert project(_priced(world), mode=MODE_CLIENT)["price"] is None


def test_card_policy_cabinet_shows_list_price(world):
    item = project(_priced(world, price_visibility=PriceVisibility.CABINET), mode=MODE_CLIENT)
    assert item["price"] == {"amount": "1234.50", "currency": "USD"}


def test_company_policy_applies_to_cards_without_their_own(world):
    set_company_policy(world, catalog_price_visibility=PriceVisibility.CABINET)
    assert project(_priced(world), mode=MODE_CLIENT)["price"]["amount"] == "1234.50"


def test_card_on_request_overrides_company_cabinet(world):
    set_company_policy(world, catalog_price_visibility=PriceVisibility.CABINET)
    assert project(_priced(world, price_visibility=PriceVisibility.ON_REQUEST), mode=MODE_CLIENT)["price"] is None


def test_cabinet_without_list_price_falls_back_to_on_request(world):
    """Закупочная цена поставщика НИКОГДА не становится ценой клиенту."""
    item = project(make_card(world, price_visibility=PriceVisibility.CABINET), mode=MODE_CLIENT)
    assert item["price"] is None


def test_project_many_reads_policies_in_one_query(world, django_assert_max_num_queries):
    set_company_policy(world, catalog_price_visibility=PriceVisibility.CABINET)
    for index in range(5):
        _priced(world, name=f"Карточка {index}")
    from catalog.published import published_products

    with django_assert_max_num_queries(6):
        items = project_many(published_products(), mode=MODE_CLIENT)
    assert len(items) == 5 and all(item["price"] for item in items)


# ── 3. Наличие как статус ───────────────────────────────────────────────────────────────


def test_availability_without_offers_is_on_order_without_date(world):
    assert availability(make_card(world, offer=False)) == ("on_order", None)


def test_availability_on_order_uses_shortest_order_lead_time(world):
    product = make_card(world, offer=False)
    for lead in (30, 14):
        SupplierOffer.objects.create(
            product=product,
            supplier=Company.objects.create(name=f"Поставщик {lead}", inn=f"98200000{lead}"),
            base_price=Decimal("1"),
            order_lead_time_days=lead,
        )
    assert availability(product) == ("on_order", 14)


def test_availability_ignores_inactive_and_lapsed_offers(world):
    product = make_card(world)
    offers = SupplierOffer.objects.filter(product=product)
    offers.update(valid_until=TODAY - datetime.timedelta(days=1))
    assert availability(Product.objects.get(pk=product.pk)) == ("on_order", None), "цена истекла"
    offers.update(valid_until=None, valid_from=TODAY + datetime.timedelta(days=1))
    assert availability(Product.objects.get(pk=product.pk)) == ("on_order", None), "цена ещё не действует"
    offers.update(valid_from=None, is_active=False)
    assert availability(Product.objects.get(pk=product.pk)) == ("on_order", None), "предложение выключено"
    offers.update(is_active=True)
    assert availability(Product.objects.get(pk=product.pk)) == ("in_stock", 3)


def test_availability_expected_status(world):
    product = make_card(world)
    SupplierOffer.objects.filter(product=product).update(
        stock_quantity=0, stock_status=StockStatus.objects.get(code="EXPECTED")
    )
    assert availability(Product.objects.get(pk=product.pk)) == ("expected", 21)


# ── 4. Товар / услуга и политика исполнения ─────────────────────────────────────────────


def test_service_gets_fixed_policy_and_goods_none(world):
    service = make_card(world, name="Монтаж", service=True, offer=False)
    goods = make_card(world, name="Болт", fulfillment_policy=FulfillmentPolicy.MILESTONES)

    assert service.fulfillment_policy == FulfillmentPolicy.FIXED
    assert goods.fulfillment_policy == "", "у товара политики исполнения нет"
    assert project(service, mode=MODE_CLIENT)["kind"] == "service"


def test_service_keeps_chosen_policy(world):
    service = make_card(world, name="Обучение", service=True, offer=False, fulfillment_policy=FulfillmentPolicy.TIME)
    service.refresh_from_db()
    assert service.fulfillment_policy == FulfillmentPolicy.TIME


# ── 5. Полнота и порог публикации ───────────────────────────────────────────────────────


def test_cabinet_visibility_requires_list_price(world):
    product = make_card(world, published=False, price_visibility=PriceVisibility.CABINET)
    report = completeness(product)
    assert "list_price" in [item["code"] for item in report["missing"]]
    assert report["is_publishable"] is False

    on_request = make_card(world, name="По запросу", published=False)
    assert "list_price" not in [item["code"] for item in completeness(on_request)["missing"]]


def test_threshold_policy_allows_publishing_below_full_completeness(world):
    product = make_card(world, published=False, hs_code="")
    assert completeness(product)["is_publishable"] is False, "по умолчанию нужно всё обязательное"

    set_company_policy(world, catalog_publish_threshold=75)
    report = completeness(product)
    assert report["percent"] == 75 and report["threshold"] == 75
    assert report["is_publishable"] is True


def test_name_is_required_whatever_the_threshold(world):
    set_company_policy(world, catalog_publish_threshold=1)
    product = make_card(world, published=False)
    Product.objects.filter(pk=product.pk).update(name=" ")
    assert completeness(Product.objects.get(pk=product.pk))["is_publishable"] is False


def test_publish_endpoint_honours_threshold(world):
    product = make_card(world, published=False, hs_code="")
    url = f"/api/v1/catalog/products/{product.pk}/publish/"
    assert world["staff_client"].post(url).status_code == 400
    set_company_policy(world, catalog_publish_threshold=75)
    assert world["staff_client"].post(url).status_code == 200


# ── 6. API бэк-офиса и настройки ────────────────────────────────────────────────────────


def test_staff_card_carries_published_layer_fields_and_client_preview(world):
    product = _priced(world, price_visibility=PriceVisibility.CABINET)
    data = world["staff_client"].get(f"/api/v1/catalog/products/{product.pk}/").json()

    assert data["price_visibility"] == "cabinet"
    assert data["price_visibility_effective"] == "cabinet"
    assert data["list_price"] == "1234.50" and data["list_price_currency_code"] == "USD"
    assert data["client_preview"] == json.loads(json.dumps(project(product, mode=MODE_CLIENT)))
    assert_no_internal_layer(data["client_preview"], "client_preview")


def test_staff_sets_published_layer_and_currency_is_required(world):
    product = make_card(world)
    url = f"/api/v1/catalog/products/{product.pk}/"
    response = world["staff_client"].patch(url, {"list_price": "10.00"}, format="json")
    assert response.status_code == 400
    assert response.json()["list_price_currency"] == ["LIST_PRICE_CURRENCY_REQUIRED"]

    response = world["staff_client"].patch(
        url,
        {"list_price": "10.00", "list_price_currency": world["usd"].pk, "price_visibility": "cabinet"},
        format="json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["client_preview"]["price"] == {"amount": "10.00", "currency": "USD"}


@pytest.mark.parametrize("who", ["anonymous", "buyer"])
def test_backoffice_catalog_is_closed_to_non_staff(world, who):
    product = make_card(world)
    client = APIClient()
    if who == "buyer":
        client.force_authenticate(world["buyer"])
    for url in (
        "/api/v1/catalog/products/",
        f"/api/v1/catalog/products/{product.pk}/",
        "/api/v1/catalog/products/export/",
        "/api/v1/catalog/products/coverage/",
    ):
        assert client.get(url).status_code in (401, 403), url


def test_company_catalog_policy_is_editable_in_settings(world, grant):
    grant(world["staff"], "settings.edit")
    url = f"/api/v1/accounts/companies/{world['own'].pk}/settings/"
    client = world["staff_client"]
    data = client.get(url).json()
    assert data["catalog_price_visibility"] == "on_request"
    assert data["catalog_publish_threshold"] == 100

    response = client.patch(
        url, {"catalog_price_visibility": "cabinet", "catalog_publish_threshold": 80}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["catalog_price_visibility"] == "cabinet"
    assert response.json()["catalog_publish_threshold"] == 80

    assert client.patch(url, {"catalog_price_visibility": "everyone"}, format="json").json() == {
        "detail": "BAD_PRICE_VISIBILITY"
    }
    assert client.patch(url, {"catalog_publish_threshold": 0}, format="json").json() == {
        "detail": "BAD_PUBLISH_THRESHOLD"
    }


# ── 7. Ни один публичный или клиентский эндпоинт не отдаёт внутренний слой ─────────────

#: Маршруты, которые обход не трогает: схема OpenAPI (имена полей, а не данные) и раздача
#: медиа-файлов (не JSON и не данные карточки).
SKIPPED_ROUTE_PREFIXES = ("api/schema", "api/docs", "api/redoc", "media/", "^media/")


def _walk(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern)


def _concrete_path(route: str, values: dict) -> str | None:
    """Шаблон маршрута → путь с подставленными id; `None` — маршрут с суффиксом формата."""
    if "(?P<format>" in route:
        return None
    path = route.replace("^", "").replace("$", "")
    path = re.sub(r"\(\?P<(\w+)>[^)]*\)", lambda m: str(values.get(m.group(1), values["pk"])), path)
    path = re.sub(r"<(?:\w+:)?(\w+)>", lambda m: str(values.get(m.group(1), values["pk"])), path)
    path = path.replace("\\.", ".").replace("/?", "/")
    return "/" + path


def _every_get_path(values: dict) -> list[str]:
    paths = []
    for route in _walk(get_resolver().url_patterns):
        if route.startswith(SKIPPED_ROUTE_PREFIXES):
            continue
        path = _concrete_path(route, values)
        if path:
            paths.append(path)
    return sorted(set(paths))


@pytest.fixture
def client_world(world):
    """Опубликованная карточка с внутренним слоем + отправленное клиенту КП с её строкой."""
    from crm.models import Deal, Quote, QuoteItem, QuoteStatus

    product = _priced(world, price_visibility=PriceVisibility.CABINET)
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено", "sort_order": 50})
    deal = Deal.objects.create(company=world["client_company"])
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        frozen_at=timezone.now(),
        public_access_token=SWEEP_QUOTE_LINK,
    )
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
    QuoteItem.objects.create(
        quote=quote,
        position=1,
        product=product,
        offer=product.offers.first(),
        quantity=2,
        frozen_base_price=COST,
        frozen_currency=world["usd"],
        # С наценкой цена клиенту ≠ закупочной: метка «48213.77» в КП была бы законной ценой.
        margin_percent=Decimal("25"),
    )
    return {**world, "product": product, "deal": deal, "quote": quote}


@pytest.mark.parametrize("who", ["anonymous", "buyer"])
def test_no_route_leaks_internal_layer_to_anonymous_or_client(client_world, who, monkeypatch):
    """DoD M1-ERP-07: обход ВСЕХ GET-маршрутов ERP (включая будущие `/api/portal/*`).

    Аноним и покупательский аккаунт (клиент до портала M2-ERP-01) не получают ни одной метки
    внутреннего слоя — ни в JSON, ни в HTML публичной страницы КП, ни в выгрузках.
    """
    world = client_world
    values = {
        "pk": world["product"].pk,
        "id": world["product"].pk,
        "product_id": world["product"].pk,
        "deal_id": world["deal"].pk,
        "quote_id": world["quote"].pk,
        "token": world["quote"].public_access_token,
    }
    # Троттлинг анонима (20/мин) превратил бы обход в серию 429 — и тест проходил бы впустую.
    monkeypatch.setattr(APIView, "check_throttles", lambda self, request: None)
    client = APIClient(raise_request_exception=False)
    if who == "buyer":
        client.force_authenticate(world["buyer"])

    checked = 0
    for path in _every_get_path(values):
        for accept in ("application/json", "text/html"):
            response = client.get(path, HTTP_ACCEPT=accept, SERVER_NAME="localhost")
            if response.status_code >= 500 or getattr(response, "streaming", False):
                continue
            body = response.content.decode("utf-8", errors="ignore")
            assert_no_internal_layer(body, f"{who} GET {path} [{accept}] → {response.status_code}")
            checked += 1
    assert checked > 100, "обход должен пройти по всему API, а не по паре маршрутов"
