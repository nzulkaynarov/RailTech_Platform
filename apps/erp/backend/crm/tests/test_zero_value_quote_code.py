"""Q3 (honest errors): a zero/negative-total КП fails for two DIFFERENT reasons, and the seller
must be told which. NO billable ITEM rows → `QUOTE_EMPTY`; rows exist but price to nothing →
`QUOTE_HAS_UNPRICED_LINES`. Both the submit gate (`assert_submittable`) and the send gate
(`assert_send_economics`) route through the same `_zero_value_code` helper.
"""

from decimal import Decimal

import pytest

from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.quotes.lifecycle_gates import assert_send_economics, assert_submittable
from master_data.models import Country

pytestmark = pytest.mark.django_db


@pytest.fixture
def lookups(db):
    for code in ["DRAFT"]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})


@pytest.fixture
def empty_quote(lookups):
    deal = Deal.objects.create(title="Z", stage=DealStage.objects.get(code="DRAFT"))
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        total_incl_vat=Decimal("0.00"),
    )


# economics with no other blocker, so the gate reaches the zero-value branch only.
_CLEAN_ECON = {"fx_missing": False, "below_cost": False, "below_floor": False}


def test_submit_empty_quote_returns_quote_empty(empty_quote):
    assert assert_submittable(empty_quote, _CLEAN_ECON) == "QUOTE_EMPTY"


def test_submit_unpriced_lines_returns_unpriced_code(empty_quote):
    # A real ITEM line exists (so the КП is NOT empty) but it prices to nothing → subtotal stays 0.
    QuoteItem.objects.create(
        quote=empty_quote,
        display_type=QuoteItem.DisplayType.ITEM,
        is_optional=False,
        imported_raw_name="Штука без цены",
        quantity=Decimal("1"),
    )
    assert assert_submittable(empty_quote, _CLEAN_ECON) == "QUOTE_HAS_UNPRICED_LINES"


def test_only_section_note_rows_count_as_empty(empty_quote):
    # SECTION/NOTE carry no price and are NOT billable → the КП is still «empty» for the gate.
    QuoteItem.objects.create(quote=empty_quote, display_type=QuoteItem.DisplayType.SECTION, imported_raw_name="Раздел")
    QuoteItem.objects.create(quote=empty_quote, display_type=QuoteItem.DisplayType.NOTE, imported_raw_name="Заметка")
    assert assert_submittable(empty_quote, _CLEAN_ECON) == "QUOTE_EMPTY"


def test_send_gate_distinguishes_empty_from_unpriced(empty_quote):
    with pytest.raises(ValueError, match="QUOTE_EMPTY"):
        assert_send_economics(empty_quote, _CLEAN_ECON, "")
    QuoteItem.objects.create(
        quote=empty_quote,
        display_type=QuoteItem.DisplayType.ITEM,
        is_optional=False,
        imported_raw_name="Строка",
        quantity=Decimal("1"),
    )
    with pytest.raises(ValueError, match="QUOTE_HAS_UNPRICED_LINES"):
        assert_send_economics(empty_quote, _CLEAN_ECON, "")
