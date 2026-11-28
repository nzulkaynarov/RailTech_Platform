"""Пример из статьи помощи «Правила расчёта: как считает калькулятор КП» — цифры статьи держит реальный движок."""

from decimal import Decimal as D

import pytest
from django.utils import timezone

from accounts.models import Company
from crm.models import ChargeType, Deal, DealStage, Quote, QuoteCharge, QuoteItem, QuoteStatus
from crm.services.quotes.pricing import QuoteCalculationService, compute_quote_economics
from master_data.models import Currency, ExchangeRate


@pytest.mark.django_db
def test_article_example_numbers():
    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    status = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    deal = Deal.objects.create(title="Пример", company=Company.objects.create(name="Buyer", inn="A1"), stage=stage)
    quote = Quote.objects.create(deal=deal, version=1, status=status, vat_rate=D(12), margin_percent=D(20))
    usd = Currency.objects.update_or_create(code="USD", defaults={"name": "USD", "is_active": True})[0]
    ExchangeRate.objects.filter(currency=usd).delete()
    ExchangeRate.objects.create(currency=usd, rate_date=timezone.localdate(), rate_to_uzs=D(12000), source="TEST")
    line = {"quote": quote}
    QuoteItem.objects.create(**line, quantity=10, frozen_base_price=D(100), customs_duty=D(10), frozen_currency=usd)
    QuoteItem.objects.create(**line, quantity=4, frozen_base_price=D(500000), discount_percent=D(5))
    QuoteItem.objects.create(**line, quantity=5, frozen_base_price=D(300000), client_price_fixed=D(400000))
    freight = ChargeType.objects.get_or_create(code="FREIGHT", defaults={"name": "Доставка"})[0]
    fee = ChargeType.objects.get_or_create(code="FEE", defaults={"name": "Комиссия"})[0]
    QuoteCharge.objects.create(quote=quote, charge_type=freight, amount=D(600000), cost_amount=D(450000), sort_order=1)
    QuoteCharge.objects.create(quote=quote, charge_type=fee, rate_percent=D(5), sort_order=2)

    quote = QuoteCalculationService.recalculate_quote(quote.pk)
    assert [i.final_price_excl_vat for i in quote.items.order_by("id")] == [D(1584000), D(570000), D(400000)]
    assert (quote.subtotal_excl_vat, quote.charges_total) == (D(20120000), D(1636000))
    assert (quote.vat_amount, quote.total_incl_vat) == (D(2610720), D(24366720))

    eco = compute_quote_economics(quote)  # порог маржи по умолчанию — 15 %
    assert (eco["total_landed_cost"], eco["gross_profit"]) == (D(16700000), D(3420000))
    assert (eco["gross_margin_percent"], eco["markup_percent"]) == (D("17.0"), D("20.5"))
    assert (eco["charge_cost_total"], eco["operating_profit"]) == (D(1486000), D(3570000))
    assert not eco["below_floor"] and not eco["below_cost"]
