"""Число запросов списков портала не растёт с числом записей (FIX-25, хвосты ревью FIX-21…23).

Каждый тест снимает число запросов на мире фикстур, добавляет несколько записей «того же вида» и требует, чтобы
повторный запрос уложился в то же число (`django_assert_max_num_queries`). Без правки число растёт на запись.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from portal.tests.contract_world import TODAY, _stage, _status, make_quote

from catalog.models import Category, Product, ProductStatus
from crm.constants import ActStatusCode, ContractStatusCode, DealStageCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import Act, ActStatus, Contract, ContractStatus, Deal, Invoice, InvoiceStatus, QuoteItem
from master_data.models import UnitOfMeasure

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
MORE = 5


def queries(client, url: str) -> int:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(f"{API}{url}")
    assert response.status_code == 200, response.content[:200]
    return len(captured)


def test_quote_lines_do_not_query_the_unit_per_product(contract_world, portal_client, django_assert_max_num_queries):
    """Единица строки без своей `unit` берётся из карточки каталога — `product.uom` одним запросом на все строки."""
    quote = contract_world["quotes"]["accepted"]  # принятое КП: просмотр не пишет `first_viewed_at`
    url = f"/quotes/{quote.pk}"
    baseline = queries(portal_client, url)
    category = Category.objects.first()
    for index in range(MORE):
        unit = UnitOfMeasure.objects.create(code=f"unit-{index}", name=f"ед{index}")
        product = Product.objects.create(
            name=f"Товар {index}",
            sku=f"SKU-N1-{index}",
            category=category,
            uom=unit,
            status=_status(ProductStatus, "PUBLISHED"),
        )
        QuoteItem.objects.create(
            quote=quote,
            display_type="ITEM",
            product=product,
            imported_raw_name=f"Строка {index}",
            quantity=2,
            unit="",
            frozen_base_price=Decimal("1000"),
            position=10 + index,
        )
    body = portal_client.get(f"{API}{url}").json()
    assert {line["unit"] for line in body["lines"] if line["title"].startswith("Товар")} >= {
        f"ед{i}" for i in range(MORE)
    }
    with django_assert_max_num_queries(baseline):
        portal_client.get(f"{API}{url}")


def test_invoice_list_resolves_due_days_once_per_seller(contract_world, portal_client, django_assert_max_num_queries):
    """Счета без срока оплаты считают его правилом выставления; срок продавца ищется один раз, а не на каждый счёт."""
    baseline = queries(portal_client, "/invoices")
    main = contract_world["main"]
    contract = contract_world["contracts"]["signed"]
    for index in range(MORE):
        Invoice.objects.create(
            deal=main,
            contract=contract,
            number=f"INV-N1-{index}",
            status=_status(InvoiceStatus, InvoiceStatusCode.ISSUED),
            due_date=None,
            issued_at=TODAY - datetime.timedelta(days=index),
            total_incl_vat=Decimal("1000"),
            currency=contract_world["uzs"],
        )
    items = portal_client.get(f"{API}/invoices").json()
    assert len([i for i in items if i["number"].startswith("INV-N1-")]) == MORE
    with django_assert_max_num_queries(baseline):
        portal_client.get(f"{API}/invoices")


def test_invoice_due_date_follows_the_sellers_terms(contract_world, portal_client, seller_company):
    """Срок продавца применяется ко всем счетам без срока, а не только к первому (кэш по продавцу не врёт)."""
    settings_row = seller_company.settings
    settings_row.payment_terms_days = 30
    settings_row.save(update_fields=["payment_terms_days"])
    from crm.models import Quote

    Quote.objects.filter(pk=contract_world["quotes"]["accepted"].pk).update(seller_company=seller_company)
    contract = contract_world["contracts"]["signed"]
    for index in range(3):
        Invoice.objects.create(
            deal=contract_world["main"],
            contract=contract,
            number=f"INV-N1-T{index}",
            status=_status(InvoiceStatus, InvoiceStatusCode.ISSUED),
            due_date=None,
            issued_at=TODAY,
            total_incl_vat=Decimal("1000"),
            currency=contract_world["uzs"],
        )
    items = [i for i in portal_client.get(f"{API}/invoices").json() if i["number"].startswith("INV-N1-T")]
    assert len(items) == 3
    assert {i["due_date"] for i in items} == {(TODAY + datetime.timedelta(days=30)).isoformat()}


def test_document_list_loads_deal_refs_in_the_same_queries(
    contract_world, portal_client, django_assert_max_num_queries
):
    """`DealRef` каждого документа приходит с самой записью (`select_related("deal")`), по запросу на сделку не ходим."""
    baseline = queries(portal_client, "/documents")
    for index in range(MORE):
        deal = Deal.objects.create(
            company=contract_world["company"],
            contact=contract_world["contact"],
            title=f"Сделка N1-{index}",
            stage=_stage(DealStageCode.CONTRACT_SIGNED),
        )
        quote = make_quote(deal, 1, QuoteStatusCode.APPROVED, uzs=contract_world["uzs"])
        Contract.objects.create(
            deal=deal,
            quote=quote,
            number=f"CT-N1-{index}",
            status=_status(ContractStatus, ContractStatusCode.SIGNED),
            total_amount=Decimal("1000"),
            currency=contract_world["uzs"],
        )
        invoice = Invoice.objects.create(
            deal=deal,
            number=f"INV-N1D-{index}",
            status=_status(InvoiceStatus, InvoiceStatusCode.ISSUED),
            due_date=TODAY,
            issued_at=TODAY,
            total_incl_vat=Decimal("1000"),
            currency=contract_world["uzs"],
        )
        Act.objects.create(
            deal=deal,
            invoice=invoice,
            number=f"ACT-N1-{index}",
            status=_status(ActStatus, ActStatusCode.ISSUED),
            issued_at=TODAY,
            total_amount=Decimal("1000"),
        )
    titles = {item["deal"]["title"] for item in portal_client.get(f"{API}/documents").json() if item["deal"]}
    assert {f"Сделка N1-{i}" for i in range(MORE)} <= titles
    with django_assert_max_num_queries(baseline):
        portal_client.get(f"{API}/documents")
