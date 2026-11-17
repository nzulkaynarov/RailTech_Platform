"""ADR-0027 пп. 9–10: строка расчёта — дробное количество (12,5 т) и единица из справочника; цена и сумма считаются от
дробного количества, копия прошлого расчёта переносит код единицы."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sales.models import QuoteItem

from core.models import UnitOfMeasure
from crm.tests.test_calc import _api, _url, world  # noqa: F401  # фикстура мира расчёта

pytestmark = pytest.mark.django_db


@pytest.fixture
def tonne(db):
    return UnitOfMeasure.objects.get_or_create(code="TNE", defaults={"name": "т", "sort_order": 50})[0]


def _line(world, quantity):  # noqa: F811
    supply = _api(world["supply"])
    assert supply.post(_url(world, "start/")).status_code == 200
    response = supply.post(
        _url(world, "lines/"), {"lines": [{"name": "Рельс Р65", "quantity": quantity}]}, format="json"
    )
    assert response.status_code == 201, response.json()
    return response.json()["created"][0]


def test_fractional_quantity_is_stored_and_returned_as_a_number(world):  # noqa: F811
    line_id = _line(world, 12.5)
    assert QuoteItem.objects.get(pk=line_id).quantity == Decimal("12.500")
    lines = {line["id"]: line for line in _api(world["supply"]).get(_url(world)).json()["lines"]}
    assert lines[line_id]["quantity"] == 12.5


def test_quantity_patch_accepts_three_decimals_and_refuses_more(world):  # noqa: F811
    line_id = _line(world, 1)
    supply = _api(world["supply"])
    assert supply.patch(_url(world, f"lines/{line_id}/"), {"quantity": 0.125}, format="json").status_code == 200
    assert QuoteItem.objects.get(pk=line_id).quantity == Decimal("0.125")
    assert supply.patch(_url(world, f"lines/{line_id}/"), {"quantity": 0.0001}, format="json").status_code == 400


def test_line_total_follows_the_fractional_quantity(world):  # noqa: F811
    line_id = _line(world, 12.5)
    supply = _api(world["supply"])
    body = {"purchase_price": "1000", "client_price": "1200", "purchase_currency": "UZS"}
    assert supply.patch(_url(world, f"lines/{line_id}/"), body, format="json").status_code == 200
    item = QuoteItem.objects.get(pk=line_id)
    assert item.line_total == item.final_price_excl_vat * Decimal("12.5")


def test_unit_comes_from_the_dictionary(world, tonne):  # noqa: F811
    line_id = _line(world, 2)
    supply = _api(world["supply"])
    response = supply.patch(_url(world, f"lines/{line_id}/"), {"unit_code": "TNE"}, format="json")
    assert response.status_code == 200, response.json()
    line = next(line for line in response.json()["lines"] if line["id"] == line_id)
    assert (line["unit_code"], line["unit"]) == ("TNE", "т")
    refused = supply.patch(_url(world, f"lines/{line_id}/"), {"unit_code": "XXX"}, format="json")
    assert refused.status_code == 400 and refused.json()["detail"] == "UNIT_NOT_FOUND"
