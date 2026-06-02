"""Pure-logic tests for QuoteCalculationService.calculate_item_prices.

Runs entirely in memory (commit=False, product=None → goods branch), so no DB
is touched. Guards the core money formula:
    landed_cost = base + logistics + customs
    final_price_excl_vat = landed_cost * (1 + margin%)   (rounded HALF_UP to kopeck)
"""

from decimal import Decimal

from crm.models import QuoteItem
from crm.services import QuoteCalculationService


def _item(base, logistics, customs, margin):
    return QuoteItem(
        frozen_base_price=Decimal(base),
        logistics_cost=Decimal(logistics),
        customs_duty=Decimal(customs),
        margin_percent=Decimal(margin),
        quantity=1,
    )


class TestCalculateItemPrices:
    def test_landed_cost_sums_components(self):
        item = _item("100", "10", "5", "0")
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.landed_cost == Decimal("115")

    def test_margin_applied_to_landed_cost(self):
        item = _item("100", "10", "5", "20")  # landed 115, +20% = 138.00
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("138.00")

    def test_zero_margin_keeps_landed_cost(self):
        item = _item("250.50", "0", "0", "0")
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("250.50")

    def test_rounding_is_half_up_to_kopeck(self):
        # landed 1.005, margin 0 → 1.005 → HALF_UP → 1.01
        item = _item("1.005", "0", "0", "0")
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("1.01")

    def test_fractional_margin(self):
        item = _item("100", "0", "0", "10.5")  # 100 * 1.105 = 110.50
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("110.50")

    def test_result_always_two_decimal_places(self):
        item = _item("33.33", "0", "0", "0")
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat.as_tuple().exponent == -2
