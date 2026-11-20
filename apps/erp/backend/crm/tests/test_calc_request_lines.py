"""СЦ-10: количество и единица заявки клиента доходят до расчёта и до черновика позиции как написаны.

Прогон сценариев: «12,5 т» из кабинета в расчёте становилось «13», а у черновика позиции единицы не было.
"""

from decimal import Decimal

import pytest
from portal.models import PortalRequestLine
from sales.models import QuoteItem

from core.seeds.uom import seed_uom
from crm.tests import test_calc

pytestmark = pytest.mark.django_db

world = test_calc.world  # мир расчёта: сделка с заданием, снабженец и инженер
_api, _url = test_calc._api, test_calc._url


@pytest.fixture
def request_lines(world):
    seed_uom()
    deal = world["deal"]
    PortalRequestLine.objects.create(
        deal=deal, text="Рельс Р65, длина 25 м", quantity=Decimal("12.5"), unit="т", sort_order=1
    )
    PortalRequestLine.objects.create(deal=deal, text="Накладка стыковая Р65", quantity=400, unit="ШТ", sort_order=2)
    PortalRequestLine.objects.create(deal=deal, text="Доставка до станции", quantity=None, unit="рейс", sort_order=3)
    return deal


def _calc_items(deal):
    return list(
        QuoteItem.objects.filter(quote__deal=deal, quote__prepared_by__isnull=False)
        .select_related("product__uom", "product__status")
        .order_by("position")
    )


def test_start_keeps_the_request_quantity_and_unit(world, request_lines):
    response = _api(world["supply"]).post(_url(world, "start/"))
    assert response.status_code == 200, response.json()

    items = _calc_items(request_lines)
    assert [i.quantity for i in items] == [Decimal("12.500"), Decimal("400.000"), Decimal("1.000")]
    assert [i.unit_code for i in items] == ["TNE", "H87", ""]
    assert [i.unit for i in items] == ["т", "шт.", "рейс"]
    lines = {line["name"]: line for line in response.json()["lines"]}
    assert lines["Рельс Р65, длина 25 м"]["quantity"] == 12.5
    assert lines["Рельс Р65, длина 25 м"]["unit_code"] == "TNE"
    assert lines["Доставка до станции"]["unit_code"] is None


def test_draft_card_gets_the_request_unit(world, request_lines):
    assert _api(world["supply"]).post(_url(world, "start/")).status_code == 200

    items = _calc_items(request_lines)
    assert items[0].product.status.code == "DRAFT"
    assert items[0].product.uom.code == "TNE"
    assert items[1].product.uom.code == "H87"
    assert items[2].product.uom_id is None


def test_repeated_start_changes_nothing(world, request_lines):
    from catalog.models import Product

    supply = _api(world["supply"])
    assert supply.post(_url(world, "start/")).status_code == 200
    products, items = Product.objects.count(), len(_calc_items(request_lines))
    assert supply.post(_url(world, "start/")).status_code == 200

    assert Product.objects.count() == products
    assert len(_calc_items(request_lines)) == items


def test_non_positive_quantity_becomes_one(world):
    """Путь MCP пишет количество без проверки знака — в КП минимум 0,001, поэтому «0» и «-5» дают 1."""
    seed_uom()
    PortalRequestLine.objects.create(deal=world["deal"], text="Болт", quantity=Decimal("-5"), unit="", sort_order=1)
    assert _api(world["supply"]).post(_url(world, "start/")).status_code == 200
    assert [i.quantity for i in _calc_items(world["deal"])] == [Decimal("1.000")]


def test_bound_line_without_unit_takes_the_card_unit():
    from catalog.models import Product
    from core.models import UnitOfMeasure
    from crm.services.draft_quote import _unit_from_card

    seed_uom()
    card = Product.objects.create(name="Болт М22", uom=UnitOfMeasure.objects.get(code="KGM"))
    bare = {"product_id": card.pk, "unit": "", "unit_code": ""}
    written = {"product_id": card.pk, "unit": "т", "unit_code": ""}
    _unit_from_card(bare)
    _unit_from_card(written)
    assert (bare["unit_code"], bare["unit"]) == ("KGM", "кг")
    assert (written["unit_code"], written["unit"]) == ("", "т")
