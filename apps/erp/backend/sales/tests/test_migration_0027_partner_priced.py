"""Миграция sales/0027 на данных (РАСЧ-1): `partner_priced` ставится только строкам, чья закупка ещё равна цене
и валюте внешнего предложения. Рукой правленная закупка (до РАСЧ-1 `offer` при правке не снимался) и строка без
предложения остаются False — ложное «Партнёр · до …» хуже отсутствующего."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from parties.models import Company

from catalog.models import Product, SupplierOffer
from master_data.models import Currency

pytestmark = pytest.mark.django_db

BEFORE = [("sales", "0026_dp1_contract_remarks")]
AFTER = [("sales", "0027_calcline_partner_priced")]


def _migrate(targets):
    connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")  # отложенные FK-события мешают ALTER TABLE
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def test_0027_marks_only_lines_still_priced_from_external_offer(settings):
    old = _migrate(BEFORE)
    Deal = old.get_model("sales", "Deal")
    Quote = old.get_model("sales", "Quote")
    QuoteStatus = old.get_model("sales", "QuoteStatus")
    Item = old.get_model("sales", "QuoteItem")
    Line = old.get_model("sales", "CalcLine")

    uzs = Currency.objects.get(code="UZS")
    own = Company.objects.create(name="Своя", inn="770000099001")
    vendor = Company.objects.create(name="Партнёр", inn="770000099002")
    settings.OWN_COMPANY_ID = own.pk
    product = Product.objects.create(name="Крепление", manufacturer_part_number="КБ-0027")
    offer = SupplierOffer.objects.create(product=product, supplier=vendor, base_price=Decimal("100.00"), currency=uzs)
    quote = Quote.objects.create(
        deal=Deal.objects.create(title="Миграция 0027"),
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
    )

    def line(price, with_offer=True):
        item = Item.objects.create(
            quote=quote,
            frozen_base_price=Decimal(price),
            frozen_currency_id=uzs.pk,
            offer_id=offer.pk if with_offer else None,
        )
        return Line.objects.create(item=item).pk

    same, edited, no_offer = (
        line("100.00"),
        line("99.00"),
        line("100.00", with_offer=False),
    )

    new = _migrate(AFTER)

    Line = new.get_model("sales", "CalcLine")
    assert Line.objects.get(pk=same).partner_priced is True
    assert Line.objects.get(pk=edited).partner_priced is False, "цену правили руками — источника нет"
    assert Line.objects.get(pk=no_offer).partner_priced is False
