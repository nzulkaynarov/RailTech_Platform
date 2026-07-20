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
    def test_landed_cost_is_base_plus_customs_only(self):
        # F3.8: per-line cost = себестоимость (base) + customs (ТНВЭД) only. The logistics
        # arg (10) is NOT a per-line cost any more — freight is a document-level charge.
        item = _item("100", "10", "5", "0")
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.landed_cost == Decimal("105")  # 100 base + 5 customs; logistics excluded
        assert item.logistics_cost == Decimal("0")

    def test_margin_applied_to_landed_cost(self):
        item = _item("100", "10", "5", "20")  # landed = 100 + 5 = 105, +20% = 126.00
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("126.00")

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

    def test_line_discount_applied_after_margin(self):
        # landed 100, +20% = 120 gross, −10% discount = 108.00
        item = _item("100", "0", "0", "20")
        item.discount_percent = Decimal("10")
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("108.00")

    def test_zero_discount_keeps_gross(self):
        item = _item("100", "0", "0", "20")  # discount default 0 → 120.00
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("120.00")


class TestDeploy1TransitionalNullMarginGuard:
    """DEPLOY-1 (expand/contract for DT1): this pre-DT1 code must survive the moment the DT1
    schema migration NULLs every QuoteItem.margin_percent while this code is still serving.

    A NULL per-line margin must NOT crash `None / 100` and must INHERIT the КП-level margin
    (never honour a per-line override — that arrives with the DT1 code in Deploy 2). On today's
    NOT-NULL data the guard is dead, so these assertions also pin price-neutrality vs current prod.
    """

    def test_null_margin_does_not_crash_and_inherits_quote_margin(self):
        # After the migration a loaded item carries margin_percent=None. The save() path calls
        # calculate_item_prices(item, margin_percent=None) → must inherit, not divide None.
        from crm.models import Quote

        item = _item("100", "0", "0", "0")
        item.margin_percent = None  # simulate the NULLed column post-migration
        # A loaded item has quote_id set; assign a pk'd in-memory КП so the FK cache resolves
        # margin without a DB hit (mirrors the runtime save() path where item.quote is present).
        item.quote = Quote(id=999, margin_percent=Decimal("20"))
        assert item.quote_id == 999
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("120.00")  # 100 landed, inherited +20%

    def test_null_margin_without_quote_falls_back_to_zero_not_crash(self):
        # Defensive: a NULL margin on an item with no quote reference must still not crash.
        item = _item("250.50", "0", "0", "0")
        item.margin_percent = None
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("250.50")  # 0% fallback keeps landed cost

    def test_existing_notnull_margin_is_untouched_price_neutral(self):
        # The guard is dormant when the value is present: identical to test_margin_applied.
        item = _item("100", "10", "5", "20")  # landed 105, +20% = 126.00
        QuoteCalculationService.calculate_item_prices(item, commit=False)
        assert item.final_price_excl_vat == Decimal("126.00")
