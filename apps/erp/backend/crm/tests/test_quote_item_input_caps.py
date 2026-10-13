"""E2 (spec 2026-07-12): sanity upper caps on КП line quantity/price.

A fat-finger / paste-into-wrong-field can create an absurd deal (qty=1 500 000 or a
price of 10^12) that distorts economics and the credit meter. The QuoteItemSerializer
enforces settings-driven upper caps and rejects over-cap input with a value-comparable
code (QUOTE_ITEM_QTY_TOO_LARGE / QUOTE_ITEM_PRICE_TOO_LARGE). The lower bound (0/1) is
already guarded by the model's MinValueValidator (KP-04), auto-mapped onto the fields.

These validate serializer field-level checks directly (partial=True), so no DB rows are
needed — the caps live on the field validators, not in a service.
"""

from decimal import Decimal

from django.conf import settings
from django.test import override_settings

from crm.serializers import QuoteItemSerializer

MAX_QTY = settings.QUOTE_ITEM_MAX_QUANTITY
MAX_PRICE = settings.QUOTE_ITEM_MAX_UNIT_PRICE


def _validate(data):
    serializer = QuoteItemSerializer(data=data, partial=True)
    return serializer.is_valid(), serializer.errors


# ── quantity ────────────────────────────────────────────────────────────────
def test_quantity_at_cap_passes():
    ok, errors = _validate({"quantity": MAX_QTY})
    assert ok, errors


def test_quantity_over_cap_rejected_with_code():
    ok, errors = _validate({"quantity": MAX_QTY + 1})
    assert not ok
    assert "QUOTE_ITEM_QTY_TOO_LARGE" in str(errors["quantity"])


def test_quantity_negative_rejected():
    ok, errors = _validate({"quantity": -5})
    assert not ok
    assert "quantity" in errors


def test_quantity_spec_regression_value_rejected():
    # The exact value the eyes-on run accepted (deal #25) must now be refused.
    ok, errors = _validate({"quantity": 1500000})
    assert not ok
    assert "QUOTE_ITEM_QTY_TOO_LARGE" in str(errors["quantity"])


# ── price fields ──────────────────────────────────────────────────────────────
def test_base_price_at_cap_passes():
    ok, errors = _validate({"frozen_base_price": MAX_PRICE})
    assert ok, errors


def test_base_price_over_cap_rejected_with_code():
    ok, errors = _validate({"frozen_base_price": MAX_PRICE + 1})
    assert not ok
    assert "QUOTE_ITEM_PRICE_TOO_LARGE" in str(errors["frozen_base_price"])


def test_base_price_negative_rejected():
    ok, errors = _validate({"frozen_base_price": Decimal("-1")})
    assert not ok
    assert "frozen_base_price" in errors


def test_logistics_cost_over_cap_rejected_with_code():
    ok, errors = _validate({"logistics_cost": MAX_PRICE + 1})
    assert not ok
    assert "QUOTE_ITEM_PRICE_TOO_LARGE" in str(errors["logistics_cost"])


def test_customs_duty_over_cap_rejected_with_code():
    ok, errors = _validate({"customs_duty": MAX_PRICE + 1})
    assert not ok
    assert "QUOTE_ITEM_PRICE_TOO_LARGE" in str(errors["customs_duty"])


# ── caps are settings-driven (Rule 2) ────────────────────────────────────────
@override_settings(QUOTE_ITEM_MAX_QUANTITY=10)
def test_quantity_cap_honours_settings():
    assert _validate({"quantity": 10})[0]
    ok, errors = _validate({"quantity": 11})
    assert not ok
    assert "QUOTE_ITEM_QTY_TOO_LARGE" in str(errors["quantity"])


@override_settings(QUOTE_ITEM_MAX_UNIT_PRICE=Decimal("100"))
def test_price_cap_honours_settings():
    assert _validate({"frozen_base_price": Decimal("100")})[0]
    ok, errors = _validate({"frozen_base_price": Decimal("101")})
    assert not ok
    assert "QUOTE_ITEM_PRICE_TOO_LARGE" in str(errors["frozen_base_price"])
