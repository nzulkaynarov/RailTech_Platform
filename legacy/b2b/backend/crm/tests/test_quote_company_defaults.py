"""A new КП inherits the seller company's CompanySettings defaults — on CREATE only,
never overwriting values already set on the quote.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanySettings, CustomUser
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.services.quotes import apply_company_quote_defaults
from master_data.models import Currency, DeliveryBasis

pytestmark = pytest.mark.django_db


def _deal_and_quote():
    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 1})[0]
    qstatus = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "D", "sort_order": 1})[0]
    buyer_company = Company.objects.create(name="Buyer", inn="5000000001")
    user = CustomUser.objects.create_user(email="d@example.com", username="d@example.com", password="pw")
    deal = Deal.objects.create(title="D", company=buyer_company, client=user, stage=stage)
    quote = Quote.objects.create(deal=deal, version=1, status=qstatus)
    return quote


def _seller_with_settings(**settings_kwargs):
    seller = Company.objects.create(name="Seller", inn="5000000002")
    CompanySettings.objects.create(company=seller, **settings_kwargs)
    return seller


def test_new_quote_inherits_company_defaults():
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "sort_order": 1})[0]
    fca = DeliveryBasis.objects.get_or_create(code="FCA", defaults={"name": "FCA", "sort_order": 1})[0]
    seller = _seller_with_settings(
        default_delivery_basis=fca,
        default_cost_currency=usd,
        default_vat_rate=Decimal("0.00"),
        default_margin_percent=Decimal("18.00"),
        default_offer_validity_days=21,
    )
    quote = _deal_and_quote()

    apply_company_quote_defaults(quote, seller)
    quote.refresh_from_db()

    assert quote.delivery_basis_id == fca.id
    assert quote.cost_currency_default_id == usd.id
    assert quote.vat_rate == Decimal("0.00")
    assert quote.margin_percent == Decimal("18.00")
    assert quote.valid_until == timezone.localdate() + timedelta(days=21)


def test_defaults_never_overwrite_existing_quote_values():
    eur = Currency.objects.get_or_create(code="EUR", defaults={"name": "EUR", "sort_order": 2})[0]
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "sort_order": 1})[0]
    seller = _seller_with_settings(default_cost_currency=usd, default_margin_percent=Decimal("18.00"))
    quote = _deal_and_quote()
    # Already-set values must survive.
    quote.cost_currency_default = eur
    quote.margin_percent = Decimal("5.00")
    quote.save(update_fields=["cost_currency_default", "margin_percent"])

    apply_company_quote_defaults(quote, seller)
    quote.refresh_from_db()

    assert quote.cost_currency_default_id == eur.id  # not overwritten
    assert quote.margin_percent == Decimal("5.00")  # not overwritten


def test_no_settings_is_noop():
    seller = Company.objects.create(name="Bare", inn="5000000003")  # no CompanySettings row
    quote = _deal_and_quote()
    apply_company_quote_defaults(quote, seller)
    quote.refresh_from_db()
    assert quote.delivery_basis_id is None
    assert quote.valid_until is None
