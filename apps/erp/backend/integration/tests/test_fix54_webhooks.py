"""FIX-54 (I-20, I-21): ссылки и валюта в событиях quote.sent / invoice.* берутся из настроек и из документа, не зашиты.

События проходят `events.schema.json` (в тестах режим strict — `conftest._events_contract_strict`), дата счёта —
бизнес-дата Ташкента, а не UTC.
"""

import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from core.models import Currency
from django.utils import timezone
from integration.models import CrmClientMapping
from integration.services.webhooks import emit_invoice_event, emit_quote_sent
from parties.models import Company

from crm.constants import DealStageCode
from crm.models import Deal, DealStage, Invoice, InvoiceStatus, Quote, QuoteStatus


@pytest.fixture
def deal(db):
    company = Company.objects.create(name="ООО ТестТранс", inn="123456789")
    CrmClientMapping.objects.create(company=company, crm_client_id=42)
    stage = DealStage.objects.get_or_create(code=DealStageCode.DRAFT, defaults={"name": "Черновик"})[0]
    return Deal.objects.create(company=company, stage=stage)


def _sent_quote(deal, currency=None, token="tok-fix54"):
    sent = QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено"})[0]
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=sent,
        total_incl_vat=Decimal("1200.00"),
        quote_currency=currency,
        public_access_token=token,
    )


def test_quote_sent_link_is_the_public_quote_page_from_settings(deal, settings):
    settings.FRONTEND_URL = "http://erp.test.localhost"
    quote = _sent_quote(deal)
    with patch("integration.signals.webhooks.emit_quote_sent"):  # сигнал не шлёт своё событие
        event = emit_quote_sent(quote=quote, send_async=False)
    url = event.payload["payload"]["public_url"]
    assert url == "http://erp.test.localhost/api/v1/public/quotes/tok-fix54/"
    assert "railtech.uz" not in url


def test_quote_sent_currency_is_the_quote_currency(deal):
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар США"})[0]
    quote = _sent_quote(deal, currency=usd)
    with patch("integration.signals.webhooks.emit_quote_sent"):
        event = emit_quote_sent(quote=quote, send_async=False)
    assert event.payload["payload"]["currency"] == "USD"


def test_quote_sent_currency_defaults_to_uzs_without_quote_currency(deal):
    quote = _sent_quote(deal)
    with patch("integration.signals.webhooks.emit_quote_sent"):
        event = emit_quote_sent(quote=quote, send_async=False)
    assert event.payload["payload"]["currency"] == "UZS"


def test_invoice_link_comes_from_cabinet_url_setting(deal, settings):
    settings.CABINET_URL = "http://cabinet.test.localhost/"
    status = InvoiceStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Выставлен"})[0]
    invoice = Invoice.objects.create(deal=deal, number="INV-F54", status=status, due_date=datetime.date(2026, 11, 5))
    with patch("integration.signals.webhooks.emit_invoice_event"):
        event = emit_invoice_event("invoice.issued", invoice=invoice, send_async=False)
    link = event.payload["payload"]["link"]
    assert link == f"http://cabinet.test.localhost/invoices/{invoice.id}"
    assert "railtech.uz" not in link


def test_invoice_without_due_date_gets_the_tashkent_business_date(deal):
    """23:30 UTC — в Ташкенте (UTC+5) уже следующий день."""
    status = InvoiceStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Выставлен"})[0]
    invoice = Invoice.objects.create(deal=deal, number="INV-F54-2", status=status, due_date=None)
    moment = datetime.datetime(2026, 11, 3, 23, 30, tzinfo=datetime.timezone.utc)
    with patch("integration.signals.webhooks.emit_invoice_event"), patch.object(timezone, "now", return_value=moment):
        event = emit_invoice_event("invoice.issued", invoice=invoice, send_async=False)
    assert event.payload["payload"]["due_date"] == "2026-11-04"


def test_quote_sent_without_public_token_links_to_the_cabinet_quote_card(deal, settings):
    settings.CABINET_URL = "http://cabinet.test.localhost"
    quote = _sent_quote(deal, token=None)
    with patch("integration.signals.webhooks.emit_quote_sent"):
        event = emit_quote_sent(quote=quote, send_async=False)
    assert event.payload["payload"]["public_url"] == f"http://cabinet.test.localhost/quotes/{quote.id}"
