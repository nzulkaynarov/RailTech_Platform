"""R1 — контракт СПИСКА «Номенклатуры»: список обязан говорить правду.

Волна R1 переводит очередь наполнения на СЕРВЕРНУЮ пагинацию, а значит всё, что раньше
дотягивал клиент, обязано быть честным на бэкенде:

* сортировка действительно сортирует (`?ordering=` был молчаливым no-op — бэкенд не подключал
  `OrderingFilter`, и клик по заголовку колонки не менял ничего);
* цена не врёт: «нет оффера» — это `null`, а не строка "0" (та рендерилась как настоящая цена
  ноль), и у цены есть СВОЯ валюта, а не подставленный фронтендом UZS;
* страница стоит фиксированное число запросов — иначе `page_size=200` (столько просит очередь
  наполнения) разворачивался в сотни обращений к справочникам.
"""

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import DomainType, Product, ProductStatus, SupplierOffer
from master_data.models import Currency, HSCode

pytestmark = pytest.mark.django_db

PRODUCTS_URL = "/api/v1/catalog/products/"
YESTERDAY = datetime.date.today() - datetime.timedelta(days=1)

#: Код есть в справочнике и действует / есть, но выведен из редакции. Оба нужны, чтобы путь
#: полноты шёл по ДОРОГОЙ ветке (наполненный классификатор), а не по «справочник пуст».
LIVE_HS = "8482100000"
RETIRED_HS = "8607191000"


@pytest.fixture
def world(db, grant):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован"), ("ARCHIVED", "Архив")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    domain, _ = DomainType.objects.get_or_create(
        code="GENERAL_GOODS",
        defaults={"name": "Товары", "sku_prefix": "GD", "sort_order": 10},
    )
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    owner_role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})

    HSCode.objects.create(code=LIVE_HS, name="Подшипники шариковые прочие", level=10)
    HSCode.objects.create(code=RETIRED_HS, name="Оси в сборе", level=10, valid_until=YESTERDAY)

    usd, _ = Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар США", "symbol": "$"})
    uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "symbol": "сўм"})

    seller_company = Company.objects.create(name="ООО Р1 Продавец", inn="9700000001")
    seller_company.types.add(supplier_type)
    seller = CustomUser.objects.create_user(email="r1.seller@test.uz", username="r1.seller@test.uz", password="pw")
    CompanyMember.objects.create(
        user=seller, company=seller_company, role=owner_role, is_active=True, is_primary=True, can_sell=True
    )
    # M1-ERP-07: цены поставщиков — внутренний слой; их видит роль с правом себестоимости/каталога.
    grant(seller, "CATALOG_SUPPLY")

    outsider = CustomUser.objects.create_user(email="r1.other@test.uz", username="r1.other@test.uz", password="pw")

    seller_client = APIClient()
    seller_client.force_authenticate(seller)
    outsider_client = APIClient()
    outsider_client.force_authenticate(outsider)

    return {
        "domain": domain,
        "company": seller_company,
        "seller": seller,
        "outsider": outsider,
        "client": seller_client,
        "outsider_client": outsider_client,
        "usd": usd,
        "uzs": uzs,
    }


def make_card(world, name, *, demand=0, hs_code=LIVE_HS, published=False, offer=None):
    """Карточка ж/д домена — то есть по ДОРОГОЙ ветке полноты (проверка ТН ВЭД)."""
    product = Product.objects.create(
        name=name,
        owner_company=world["company"],
        domain_type=world["domain"],
        hs_code=hs_code,
        demand_count=demand,
        status=ProductStatus.objects.get(code="PUBLISHED" if published else "DRAFT"),
    )
    if offer is not None:
        price, currency = offer
        SupplierOffer.objects.create(
            product=product, supplier=world["company"], base_price=Decimal(price), currency=currency
        )
    return product


def names(response) -> list[str]:
    return [row["name"] for row in response.json()["results"]]


# ── 1. Сортировка ────────────────────────────────────────────────────────────────────────


def test_ordering_by_name_actually_reorders(world):
    make_card(world, "Букса")
    make_card(world, "Автосцепка")
    make_card(world, "Втулка")

    response = world["client"].get(PRODUCTS_URL, {"ordering": "name"})

    assert response.status_code == 200
    assert names(response) == ["Автосцепка", "Букса", "Втулка"]
    assert names(world["client"].get(PRODUCTS_URL, {"ordering": "-name"})) == ["Втулка", "Букса", "Автосцепка"]


def test_ordering_by_demand_count_actually_reorders(world):
    make_card(world, "Редкая", demand=1)
    make_card(world, "Ходовая", demand=42)
    make_card(world, "Средняя", demand=7)

    response = world["client"].get(PRODUCTS_URL, {"ordering": "-demand_count"})

    assert response.status_code == 200
    assert names(response) == ["Ходовая", "Средняя", "Редкая"]


def test_unlisted_ordering_field_is_ignored_not_a_500(world):
    """Поле вне белого списка не роняет запрос и не переставляет выдачу."""
    make_card(world, "Букса")
    make_card(world, "Автосцепка")

    response = world["client"].get(PRODUCTS_URL, {"ordering": "hs_code"})

    assert response.status_code == 200
    assert names(response) == ["Автосцепка", "Букса"], "остаётся сортировка по умолчанию (name)"


def test_legacy_order_demand_still_works(world):
    """`catalogApi.getMyCandidates` шлёт `?order=demand` — ветку ломать нельзя."""
    make_card(world, "Абрикос", demand=1)
    make_card(world, "Яблоко", demand=99)

    response = world["client"].get(PRODUCTS_URL, {"order": "demand"})

    assert response.status_code == 200
    assert names(response) == ["Яблоко", "Абрикос"], "спрос важнее алфавита"


def test_explicit_ordering_beats_legacy_order(world):
    """Выбор человека (`?ordering=`) сильнее умолчания очереди (`?order=demand`)."""
    make_card(world, "Абрикос", demand=1)
    make_card(world, "Яблоко", demand=99)

    response = world["client"].get(PRODUCTS_URL, {"order": "demand", "ordering": "name"})

    assert response.status_code == 200
    assert names(response) == ["Абрикос", "Яблоко"]


# ── 2. Цена перестала врать ──────────────────────────────────────────────────────────────


def test_card_without_an_offer_has_null_price_not_zero(world):
    make_card(world, "Без предложения")

    row = world["client"].get(PRODUCTS_URL).json()["results"][0]

    assert row["base_price"] is None, "«нет оффера» и «стоит ноль» — разные вещи"
    assert row["base_price_currency"] is None


def test_price_carries_the_currency_of_its_own_offer(world):
    make_card(world, "Долларовая", offer=("1250.00", world["usd"]))
    make_card(world, "Сумовая", offer=("15000000.00", world["uzs"]))

    rows = {row["name"]: row for row in world["client"].get(PRODUCTS_URL, {"ordering": "name"}).json()["results"]}

    assert rows["Долларовая"]["base_price"] == "1250.00"
    assert rows["Долларовая"]["base_price_currency"] == "USD"
    assert rows["Сумовая"]["base_price_currency"] == "UZS"


def test_currency_comes_from_the_same_offer_as_the_price(world):
    """Оффер выбирается один и тот же (самый дешёвый активный) — цена и валюта не разъезжаются."""
    card = make_card(world, "Два предложения", offer=("900.00", world["usd"]))
    rival = Company.objects.create(name="ООО Второй поставщик", inn="9700000002")
    SupplierOffer.objects.create(product=card, supplier=rival, base_price=Decimal("20000000.00"), currency=world["uzs"])

    row = world["client"].get(PRODUCTS_URL).json()["results"][0]

    assert row["base_price"] == "900.00"
    assert row["base_price_currency"] == "USD", "валюта того же оффера, что дал цену"


def test_cost_gate_strips_price_and_its_currency_together(world):
    """Валюта — часть закрытой цены: показать «USD» без цены значит рассказать о цене."""
    make_card(world, "Чужая карточка", published=True, offer=("1250.00", world["usd"]))

    row = world["outsider_client"].get(PRODUCTS_URL).json()["results"][0]

    assert "base_price" not in row
    assert "base_price_currency" not in row
    owner_row = world["client"].get(PRODUCTS_URL).json()["results"][0]
    assert owner_row["base_price_currency"] == "USD", "владельцу оба поля видны"


# ── 3. Плоская стоимость страницы (тот самый N+1) ────────────────────────────────────────


def test_list_query_count_does_not_grow_with_the_page(world, django_assert_num_queries):
    """Главный тест волны: страница стоит СТОЛЬКО ЖЕ запросов, сколько и втрое меньшая.

    До R1 каждая строка платила отдельно: `HSCode.objects.exists()` +
    `HSCode.objects.filter(code=…)` внутри `validate_hs_code`, `EquipmentGroup.objects.exists()`
    и `product.equipment_groups.exists()` — четыре запроса на карточку. Справочники здесь
    НАПОЛНЕНЫ намеренно: именно это дорогая ветка полноты, на пустых справочниках дефект
    прячется.
    """
    client = world["client"]
    for index in range(3):
        make_card(world, f"Карточка {index:02d}", hs_code=LIVE_HS if index % 2 else RETIRED_HS)

    client.get(PRODUCTS_URL, {"page_size": 200})  # прогрев: ленивые импорты и кэш прав
    with CaptureQueriesContext(connection) as captured:
        small = client.get(PRODUCTS_URL, {"page_size": 200})
    baseline = len(captured.captured_queries)
    assert small.json()["count"] == 3

    for index in range(3, 21):
        make_card(world, f"Карточка {index:02d}", hs_code=LIVE_HS if index % 2 else RETIRED_HS)

    with django_assert_num_queries(baseline):
        large = client.get(PRODUCTS_URL, {"page_size": 200})

    assert large.json()["count"] == 21, "страница выросла в 7 раз, цена запроса — нет"


def test_completeness_still_tells_the_truth_on_the_cheap_path(world):
    """Пакетная загрузка справочников не должна менять ВЕРДИКТ полноты."""
    make_card(world, "С живым кодом", hs_code=LIVE_HS)
    make_card(world, "С мёртвым кодом", hs_code=RETIRED_HS)

    rows = {row["name"]: row for row in world["client"].get(PRODUCTS_URL, {"ordering": "name"}).json()["results"]}

    missing = {name: {item["code"] for item in row["completeness"]["missing"]} for name, row in rows.items()}
    assert "hs_code" not in missing["С живым кодом"]
    assert "hs_code" in missing["С мёртвым кодом"], "код, выведенный из редакции, не считается заполненным"


# ── 5. Карточка товара отдаёт цену так же, как список ─────────────────────────────────────
#
# Список и деталь — два РАЗНЫХ сериализатора одной сущности, и правку цены легко довести
# только до одного из них. Ровно это и случилось при сборке волны: фронт карточки уже читал
# `base_price_currency`, а деталь его не отдавала — цена на карточке не отрисовалась бы
# никогда, и ни один тест списка этого бы не заметил. Тесты ниже держат оба контракта рядом.


def detail_url(product) -> str:
    return f"{PRODUCTS_URL}{product.pk}/"


def test_detail_carries_the_currency_of_its_own_offer(world):
    product = make_card(world, "Подшипник для карточки", offer=("1250.00", world["usd"]))

    body = world["client"].get(detail_url(product)).json()

    assert body["base_price"] == "1250.00"
    assert body["base_price_currency"] == "USD", "иначе карточка снова печатает доллары как сумы"


def test_detail_price_is_null_without_an_offer(world):
    product = make_card(world, "Карточка без предложения")

    body = world["client"].get(detail_url(product)).json()

    assert body["base_price"] is None, "строка '0' рендерилась как настоящая цена ноль"
    assert body["base_price_currency"] is None


def test_detail_cost_gate_strips_price_and_currency_together(world):
    product = make_card(world, "Чужая карточка", published=True, offer=("990.00", world["uzs"]))

    body = world["outsider_client"].get(detail_url(product)).json()

    assert "base_price" not in body
    assert "base_price_currency" not in body


def test_list_and_detail_agree_on_price_and_currency(world):
    """Одна цена — одно написание на обоих экранах (иначе список и карточка спорят)."""
    product = make_card(world, "Одна и та же позиция", offer=("777.50", world["usd"]))

    row = world["client"].get(f"{PRODUCTS_URL}?mine=1").json()["results"][0]
    body = world["client"].get(detail_url(product)).json()

    assert (row["base_price"], row["base_price_currency"]) == (
        body["base_price"],
        body["base_price_currency"],
    )
