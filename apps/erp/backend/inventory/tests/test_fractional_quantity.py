"""ADR-0027 п. 9: склад и снабжение считают дробное количество — 12,5 т рельса, 0,5 т в резерве; в API — число."""

from __future__ import annotations

from decimal import Decimal

import pytest
from inventory.models import StockBalance, StockMovement
from inventory.tests.test_stock import _adjust, _row

from core.quantity import as_qty, qty_text, to_qty

pytestmark = pytest.mark.django_db


def test_fractional_stock_comes_in_and_out_as_numbers(world):
    assert _adjust(world, world["rail"], 12.5).status_code == 200
    assert _adjust(world, world["rail"], -0.75).status_code == 200
    balance = StockBalance.objects.get(product=world["rail"])
    assert balance.on_hand == Decimal("11.750")
    assert _row(world, world["rail"])["on_hand"] == 11.75
    assert sorted(StockMovement.objects.values_list("quantity", flat=True)) == [Decimal("-0.750"), Decimal("12.500")]


def test_more_than_three_decimals_are_refused(world):
    assert _adjust(world, world["rail"], 0.0005).status_code == 400


def test_quantity_helpers():
    assert as_qty(Decimal("12.000")) == 12 and isinstance(as_qty(Decimal("12.000")), int)
    assert as_qty(Decimal("12.500")) == 12.5
    assert as_qty(None) is None
    assert qty_text(Decimal("150.000")) == "150" and qty_text(Decimal("0.500")) == "0.5"
    assert to_qty("12,5") == Decimal("12.500") and to_qty("1 000") == Decimal("1000.000")
