"""СЦ-10: при начале расчёта строки сначала сопоставляются с каталогом, дубль не создаётся.

Прогон сценариев: «Рельс Р65, длина 25 м» из заявки заводил вторую карточку рядом с «Рельс Р65 ГОСТ Р 51685». Теперь то же
название, записанное иначе, берёт карточку сразу, а похожее — подсказка «Похоже: …»: решает снабженец.
"""

from decimal import Decimal

import pytest
from portal.models import PortalRequestLine
from sales.models import CalcLine, QuoteItem

from catalog.models import Product, ProductStatus
from core.models import UnitOfMeasure
from core.seeds.uom import seed_uom
from crm.tests import test_calc, test_calc_catalog_link

pytestmark = pytest.mark.django_db

world = test_calc.world  # мир расчёта: своя компания — продавец `seller`
catalog_lookups = test_calc_catalog_link.catalog_lookups
_api, _url = test_calc._api, test_calc._url


@pytest.fixture
def published(world, catalog_lookups):
    seed_uom()

    def make(name, **kwargs):
        return Product.objects.create(
            name=name,
            owner_company=world["seller"],
            status=ProductStatus.objects.get(code="PUBLISHED"),
            **kwargs,
        )

    _BASELINE["ids"] = set(Product.objects.values_list("pk", flat=True))
    return make


def _request(world, text, quantity=None, unit=""):
    PortalRequestLine.objects.create(deal=world["deal"], text=text, quantity=quantity, unit=unit, sort_order=1)


def _start(world):
    response = _api(world["supply"]).post(_url(world, "start/"))
    assert response.status_code == 200, response.json()
    return response.json()


def _item(world, text):
    return QuoteItem.objects.select_related("calc", "product__uom").get(
        quote__deal=world["deal"], quote__prepared_by__isnull=False, imported_raw_name=text
    )


_BASELINE = {}


def _drafts():
    """Черновики, появившиеся в тесте (в мире расчёта уже есть карточки без владельца)."""
    return Product.objects.filter(status__code="DRAFT").exclude(pk__in=_BASELINE.get("ids", ())).count()


def test_start_binds_the_same_name_to_our_published_card(world, published):
    card = published("Накладка стыковая Р65", uom=UnitOfMeasure.objects.get(code="H87"))
    _request(world, "накладка  стыковая P65.", quantity=400)

    _start(world)

    item = _item(world, "накладка  стыковая P65.")
    assert item.product_id == card.pk
    assert item.unit_code == "H87"
    assert _drafts() == 0


def test_similar_card_is_hinted_not_duplicated(world, published, django_assert_max_num_queries):
    card = published("Рельс Р65 ГОСТ Р 51685")
    _request(world, "Рельс Р65, длина 25 м", quantity=Decimal("12.5"), unit="т")

    body = _start(world)

    item = _item(world, "Рельс Р65, длина 25 м")
    assert item.product_id is None
    assert _drafts() == 0
    [line] = [line for line in body["lines"] if line["name"] == "Рельс Р65, длина 25 м"]
    assert line["catalog_hint"] == {"id": card.pk, "name": "Рельс Р65 ГОСТ Р 51685"}
    assert line["quantity"] == 12.5


def test_hinted_line_is_still_margin_priced(world, published):
    """СЦ-10 × РАСЧ-3: подсказка создаёт строку расчёта раньше разметки — цена всё равно «от маржи», не «наценка»."""
    published("Рельс Р65 ГОСТ Р 51685")
    _request(world, "Рельс Р65, длина 25 м", quantity=1)

    _start(world)

    calc = CalcLine.objects.get(item=_item(world, "Рельс Р65, длина 25 м"))
    assert calc.catalog_hint_id is not None
    assert calc.price_basis == "margin"


def test_different_codes_are_not_hinted(world, published):
    published("Рельс Р50 длина 25 м")
    _request(world, "Рельс Р65, длина 25 м", quantity=1)

    _start(world)

    item = _item(world, "Рельс Р65, длина 25 м")
    assert item.product is not None and item.product.status.code == "DRAFT"
    assert not CalcLine.objects.filter(item=item, catalog_hint__isnull=False).exists()


def test_hint_survives_other_edits_and_repeated_start(world, published):
    published("Рельс Р65 ГОСТ Р 51685")
    _request(world, "Рельс Р65, длина 25 м", quantity=1)
    _start(world)
    item = _item(world, "Рельс Р65, длина 25 м")
    supply = _api(world["supply"])

    assert supply.post(_url(world, "lines/"), {"lines": [{"name": "Болт М22"}]}, format="json").status_code == 201
    assert supply.patch(_url(world, f"lines/{item.pk}/"), {"quantity": 3}, format="json").status_code == 200
    _start(world)

    item.refresh_from_db()
    assert item.product_id is None
    assert CalcLine.objects.get(item=item).catalog_hint_id is not None
    assert not Product.objects.filter(name="Рельс Р65, длина 25 м").exists()


def test_take_hint_binds_the_card(world, published):
    card = published("Рельс Р65 ГОСТ Р 51685")
    _request(world, "Рельс Р65, длина 25 м", quantity=1)
    _start(world)
    item = _item(world, "Рельс Р65, длина 25 м")

    response = _api(world["supply"]).patch(_url(world, f"lines/{item.pk}/"), {"product_id": card.pk}, format="json")

    assert response.status_code == 200, response.json()
    item.refresh_from_db()
    assert item.product_id == card.pk
    [line] = [line for line in response.json()["lines"] if line["id"] == item.pk]
    assert line["catalog_hint"] is None
    assert _drafts() == 0


def test_new_item_creates_one_draft_and_no_rehint(world, published):
    published("Рельс Р65 ГОСТ Р 51685")
    _request(world, "Рельс Р65, длина 25 м", quantity=1, unit="т")
    _start(world)
    item = _item(world, "Рельс Р65, длина 25 м")
    supply = _api(world["supply"])

    assert supply.patch(_url(world, f"lines/{item.pk}/"), {"product_id": None}, format="json").status_code == 200
    assert supply.patch(_url(world, f"lines/{item.pk}/"), {"product_id": None}, format="json").status_code == 200

    item = _item(world, "Рельс Р65, длина 25 м")
    assert item.product.status.code == "DRAFT" and item.product.name == "Рельс Р65, длина 25 м"
    assert item.product.uom.code == "TNE"
    assert item.product.demand_count == 1
    assert CalcLine.objects.get(item=item).catalog_hint_dismissed is True
    assert _drafts() == 1


def test_sign_waits_for_the_catalog_decision(world, published):
    card = published("Рельс Р65 ГОСТ Р 51685")
    _request(world, "Рельс Р65, длина 25 м", quantity=1)
    _start(world)
    item = _item(world, "Рельс Р65, длина 25 м")
    supply = _api(world["supply"])
    assert (
        supply.patch(
            _url(world, f"lines/{item.pk}/"), {"purchase_price": "100", "client_price": "120"}, format="json"
        ).status_code
        == 200
    )

    pending = supply.post(_url(world, f"lines/{item.pk}/visa/"))
    assert pending.status_code == 409, pending.json()
    assert "CATALOG_MATCH_PENDING" in str(pending.json())

    assert supply.patch(_url(world, f"lines/{item.pk}/"), {"product_id": card.pk}, format="json").status_code == 200
    supply.patch(_url(world, f"lines/{item.pk}/"), {"purchase_price": "100", "client_price": "120"}, format="json")
    assert supply.post(_url(world, f"lines/{item.pk}/visa/")).status_code == 200


def test_sending_links_held_lines(world, published):
    from catalog.candidates import capture_quote_lines

    published("Рельс Р65 ГОСТ Р 51685")
    _request(world, "Рельс Р65, длина 25 м", quantity=1)
    _start(world)
    item = _item(world, "Рельс Р65, длина 25 м")

    capture_quote_lines(item.quote)

    item.refresh_from_db()
    assert item.product_id is not None


@pytest.mark.parametrize(
    ("line", "card", "hinted"),
    [
        ("Рельс Р65, длина 25 м", "Рельс Р65 ГОСТ Р 51685", True),
        ("Рельс Р65, длина 25 м", "Рельс Р50 длина 25 м", False),
        ("Болт М22", "Болт М24", False),
        ("Рельс Р65", "Перевод стрелочный Р65 1/11", False),
        ("Монтаж", "Монтаж стрелочного перевода", True),
        ("Подшипник буксовый 232726", "Подшипник буксовый 42726", False),
    ],
)
def test_suggest_card_rules(world, published, line, card, hinted):
    from types import SimpleNamespace

    from catalog.candidates import suggest_card

    target = published(card)
    found = suggest_card(SimpleNamespace(imported_raw_name=line, name_canonical=""), world["seller"])
    assert (found == target) is hinted


def test_foreign_draft_and_own_archived_are_not_suggested(world, published):
    from types import SimpleNamespace

    from accounts.models import Company
    from catalog.candidates import suggest_card

    ProductStatus.objects.get_or_create(code="ARCHIVED", defaults={"name": "Архив", "sort_order": 30})
    other = Company.objects.create(name="ООО Чужой", inn="7700000999")
    Product.objects.create(name="Рельс Р65 чужой", owner_company=other)
    Product.objects.create(
        name="Рельс Р65 архив", owner_company=world["seller"], status=ProductStatus.objects.get(code="ARCHIVED")
    )
    assert suggest_card(SimpleNamespace(imported_raw_name="Рельс Р65", name_canonical=""), world["seller"]) is None


def test_added_line_with_the_same_name_is_bound_not_hinted(world, published):
    """Строка, добавленная в расчёт, с тем же названием, что у нашей карточки, связывается сразу — без подсказки."""
    card = published("Шпала ЖБ")
    _start(world)
    supply = _api(world["supply"])

    response = supply.post(_url(world, "lines/"), {"lines": [{"name": "шпала  жб"}]}, format="json")

    assert response.status_code == 201, response.json()
    item = QuoteItem.objects.get(pk=response.json()["created"][0])
    assert item.product_id == card.pk
    assert not CalcLine.objects.filter(item=item, catalog_hint__isnull=False).exists()
