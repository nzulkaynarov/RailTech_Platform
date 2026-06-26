"""КП multi-currency (per-line cost → UZS) + delivery lead-time engine tests.

Covers:
  * a USD-priced line converts to UZS via the frozen rate before the margin math
  * a КП-level manual FX override (fx_manual) wins over the snapshot / market rate
  * the КП effective delivery lead time = max(line lead times) unless overridden
"""

from decimal import Decimal

import pytest

from crm.models import Deal, Quote, QuoteItem, QuoteStatus
from crm.services import QuoteCalculationService, effective_quote_lead_time
from master_data.models import Currency

pytestmark = pytest.mark.django_db


def _company_and_deal():
    from accounts.models import Company

    company = Company.objects.create(name="ACME LLC", inn="123456789")
    deal = Deal.objects.create(company=company, title="Multi-currency test deal")
    return company, deal


def _draft_quote(deal, **kwargs):
    status = QuoteStatus.objects.filter(code="DRAFT").first()
    return Quote.objects.create(deal=deal, version=1, status=status, **kwargs)


def _usd():
    return Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$"})[0]


class TestMultiCurrencyConversion:
    def test_usd_line_converts_to_uzs_via_frozen_rate(self, monkeypatch):
        # Stub the market rate: 1 USD = 12000 UZS. base 100 USD → landed 1,200,000 UZS.
        monkeypatch.setattr("master_data.fx.get_rate_to_uzs", lambda code, on_date=None: Decimal("12000"))
        _, deal = _company_and_deal()
        usd = _usd()
        quote = _draft_quote(deal, margin_percent=Decimal("0"), vat_rate=Decimal("0"))
        item = QuoteItem(
            quote=quote,
            imported_raw_name="USD-priced widget",
            quantity=1,
            frozen_base_price=Decimal("100"),
            frozen_currency=usd,
            margin_percent=Decimal("0"),
        )
        item.save()  # triggers recalculate_quote

        item.refresh_from_db()
        quote.refresh_from_db()
        assert item.landed_cost == Decimal("1200000.00")  # 100 USD × 12000
        # margin 0 → final price == landed
        assert item.final_price_excl_vat == Decimal("1200000.00")
        # The market rate is FROZEN into the snapshot so the total can't drift later.
        assert quote.fx_snapshot.get("USD") == "12000"

    def test_margin_applied_after_conversion(self, monkeypatch):
        monkeypatch.setattr("master_data.fx.get_rate_to_uzs", lambda code, on_date=None: Decimal("12000"))
        _, deal = _company_and_deal()
        usd = _usd()
        quote = _draft_quote(deal, margin_percent=Decimal("20"), vat_rate=Decimal("0"))
        item = QuoteItem(
            quote=quote,
            imported_raw_name="USD widget +20%",
            quantity=1,
            frozen_base_price=Decimal("100"),
            frozen_currency=usd,
        )
        item.save()
        item.refresh_from_db()
        # 100 USD × 12000 = 1,200,000 UZS landed, ×1.20 margin = 1,440,000.00
        assert item.landed_cost == Decimal("1200000.00")
        assert item.final_price_excl_vat == Decimal("1440000.00")

    def test_manual_override_wins_over_market_rate(self, monkeypatch):
        # Market says 12000, but the КП pins a договорной курс of 13000 → 13000 must win.
        monkeypatch.setattr("master_data.fx.get_rate_to_uzs", lambda code, on_date=None: Decimal("12000"))
        _, deal = _company_and_deal()
        usd = _usd()
        quote = _draft_quote(
            deal, margin_percent=Decimal("0"), vat_rate=Decimal("0"), fx_manual={"USD": "13000"}
        )
        item = QuoteItem(
            quote=quote,
            imported_raw_name="USD widget manual rate",
            quantity=1,
            frozen_base_price=Decimal("100"),
            frozen_currency=usd,
        )
        item.save()
        item.refresh_from_db()
        assert item.landed_cost == Decimal("1300000.00")  # 100 × 13000

    def test_uzs_line_uses_rate_one(self):
        # A native-UZS line (frozen_currency None / UZS) is NOT converted.
        _, deal = _company_and_deal()
        quote = _draft_quote(deal, margin_percent=Decimal("0"), vat_rate=Decimal("0"))
        item = QuoteItem(
            quote=quote,
            imported_raw_name="UZS widget",
            quantity=1,
            frozen_base_price=Decimal("500000"),
        )
        item.save()
        item.refresh_from_db()
        assert item.landed_cost == Decimal("500000.00")

    def test_customs_duty_converted_in_same_line_currency(self, monkeypatch):
        # Design choice: customs_duty is treated in the SAME line currency and converted
        # together. base 100 + customs 10 = 110 USD × 12000 = 1,320,000 UZS.
        monkeypatch.setattr("master_data.fx.get_rate_to_uzs", lambda code, on_date=None: Decimal("12000"))
        _, deal = _company_and_deal()
        usd = _usd()
        quote = _draft_quote(deal, margin_percent=Decimal("0"), vat_rate=Decimal("0"))
        item = QuoteItem(
            quote=quote,
            imported_raw_name="USD widget +customs",
            quantity=1,
            frozen_base_price=Decimal("100"),
            customs_duty=Decimal("10"),
            frozen_currency=usd,
        )
        item.save()
        item.refresh_from_db()
        assert item.landed_cost == Decimal("1320000.00")

    def test_snapshot_freezes_and_survives_rate_change(self, monkeypatch):
        # First recalc freezes 12000; a later market move to 15000 must NOT change the КП.
        rate_box = {"value": Decimal("12000")}
        monkeypatch.setattr(
            "master_data.fx.get_rate_to_uzs", lambda code, on_date=None: rate_box["value"]
        )
        _, deal = _company_and_deal()
        usd = _usd()
        quote = _draft_quote(deal, margin_percent=Decimal("0"), vat_rate=Decimal("0"))
        item = QuoteItem(
            quote=quote,
            imported_raw_name="USD widget frozen",
            quantity=1,
            frozen_base_price=Decimal("100"),
            frozen_currency=usd,
        )
        item.save()
        item.refresh_from_db()
        assert item.landed_cost == Decimal("1200000.00")
        # Market jumps, but the snapshot is frozen → recalc keeps the old rate.
        rate_box["value"] = Decimal("15000")
        QuoteCalculationService.recalculate_quote(quote.pk)
        item.refresh_from_db()
        assert item.landed_cost == Decimal("1200000.00")


class TestDeliveryLeadTime:
    def test_effective_is_max_of_lines_when_no_override(self):
        _, deal = _company_and_deal()
        quote = _draft_quote(deal)
        QuoteItem(quote=quote, imported_raw_name="fast", quantity=1, lead_time_days=5).save()
        QuoteItem(quote=quote, imported_raw_name="slow", quantity=1, lead_time_days=30).save()
        quote.refresh_from_db()
        assert quote.delivery_lead_time_days is None
        assert effective_quote_lead_time(quote) == 30
        assert quote.effective_delivery_lead_time_days == 30

    def test_override_wins_over_lines(self):
        _, deal = _company_and_deal()
        quote = _draft_quote(deal, delivery_lead_time_days=14)
        QuoteItem(quote=quote, imported_raw_name="slow", quantity=1, lead_time_days=30).save()
        quote.refresh_from_db()
        assert effective_quote_lead_time(quote) == 14
        assert quote.effective_delivery_lead_time_days == 14

    def test_zero_when_no_lines_and_no_override(self):
        _, deal = _company_and_deal()
        quote = _draft_quote(deal)
        assert effective_quote_lead_time(quote) == 0
