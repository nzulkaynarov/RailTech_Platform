"""ADR-0027 п. 1 и 10: строка счёта (и акта — он печатает строки своего счёта) ссылается на карточку каталога.

Строка из КП берёт карточку и единицу строки КП; строка КП, заведённая до перехода, связывается тут же. Ручная строка —
выбранная карточка или найденная по названию либо новый черновик. Слияние дублей переносит строки счетов, черновик под
счётом не удаляется, а миграция finance/0007 связывает старые строки.
"""

from __future__ import annotations

import importlib
from decimal import Decimal

import pytest
from django.apps import apps
from django.db.models import ProtectedError
from django.test import override_settings

from catalog.candidates import drop_unused_draft
from catalog.merging import merge_products
from catalog.models import Product, ProductStatus
from crm.models import InvoiceItem, QuoteItem
from crm.services import create_manual_invoice
from crm.tests.test_manual_invoice import scenario  # noqa: F401  # сделка, КП и продавец
from master_data.models import UnitOfMeasure

pytestmark = pytest.mark.django_db

migration = importlib.import_module("finance.migrations.0007_invoice_item_product")


@pytest.fixture
def world(scenario, settings, grant):  # noqa: F811
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован"), ("ARCHIVED", "В архиве")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    settings.OWN_COMPANY_ID = scenario["seller"].pk
    grant(scenario["seller_user"], "HEAD")
    return scenario


def _card(world, name, *, status="PUBLISHED", **kwargs):
    return Product.objects.create(
        name=name, owner_company=world["seller"], status=ProductStatus.objects.get(code=status), **kwargs
    )


def _manual(world, *lines, deal="solo_deal"):
    invoice, err = create_manual_invoice(world[deal].id, world["seller_user"], lines=list(lines))
    assert err is None, err
    return list(invoice.items.order_by("pk"))


def test_text_line_gets_a_draft_card_and_the_next_invoice_reuses_it(world):
    [line] = _manual(world, {"description": "Доставка до станции", "quantity": "1.5", "unit_price_excl_vat": "10"})

    card = line.product
    assert card is not None, "строки счёта без карточки нет"
    assert card.status.code == "DRAFT" and card.owner_company_id == world["seller"].pk
    assert card.source_deal_id == world["solo_deal"].pk
    assert line.description == "Доставка до станции" and line.quantity == Decimal("1.5")

    [again] = _manual(world, {"description": "доставка до станции", "quantity": 1, "unit_price_excl_vat": "10"})
    assert again.product_id == card.pk, "тот же текст — та же карточка, дубль не плодится"
    card.refresh_from_db()
    assert card.demand_count == 2


def test_picked_card_gives_name_and_unit(world):
    tonne, _ = UnitOfMeasure.objects.get_or_create(code="TNE", defaults={"name": "т"})
    rail = _card(world, "Рельс Р65", uom=tonne)

    [line] = _manual(world, {"product_id": rail.pk, "quantity": "12.5", "unit_price_excl_vat": "100"})

    assert line.product_id == rail.pk
    assert line.description == "Рельс Р65", "без своего текста строка называется как карточка"
    assert (line.unit, line.unit_code) == ("т", "TNE")


@pytest.mark.parametrize("status", ["ARCHIVED", None])
def test_unknown_or_archived_card_is_refused(world, status):
    product_id = _card(world, "Старое", status=status).pk if status else 999_999
    invoice, err = create_manual_invoice(
        world["solo_deal"].id,
        world["seller_user"],
        lines=[{"product_id": product_id, "quantity": 1, "unit_price_excl_vat": "1"}],
    )
    assert invoice is None and err == "INVOICE_LINE_PRODUCT_INVALID"


def test_line_needs_a_card_or_a_text(world):
    invoice, err = create_manual_invoice(
        world["solo_deal"].id, world["seller_user"], lines=[{"quantity": 1, "unit_price_excl_vat": "1"}]
    )
    assert invoice is None and err == "INVOICE_LINE_DESCRIPTION_REQUIRED"


def test_quote_lines_bring_their_card_and_unit(world):
    qi = QuoteItem.objects.get(quote=world["quote"])
    QuoteItem.objects.filter(pk=qi.pk).update(unit="шт", unit_code="H87")
    assert qi.product_id is None, "строка КП до перехода — без карточки"

    invoice, err = create_manual_invoice(world["deal"].id, world["seller_user"], source_quote_id=world["quote"].id)

    assert err is None
    qi.refresh_from_db()
    [line] = list(invoice.items.all())
    assert qi.product_id is not None, "строка КП связана при выставлении счёта"
    assert line.product_id == qi.product_id
    assert (line.unit, line.unit_code) == ("шт", "H87")


def test_merge_moves_invoice_lines_and_draft_under_invoice_stays(world):
    [line] = _manual(world, {"description": "Болт М22", "quantity": 1, "unit_price_excl_vat": "1"})
    duplicate = line.product
    survivor = _card(world, "Болт путевой М22")

    assert drop_unused_draft(duplicate.pk) is False, "черновик под счётом не удаляется"
    with pytest.raises(ProtectedError):
        duplicate.delete()

    merged, err = merge_products(survivor, duplicate, world["seller_user"])
    assert err is None and merged.pk == survivor.pk
    line.refresh_from_db()
    assert line.product_id == survivor.pk, "строка счёта переехала на выжившую карточку"


def test_migration_links_old_lines(world):
    invoice, err = create_manual_invoice(world["deal"].id, world["seller_user"], source_quote_id=world["quote"].id)
    assert err is None
    from_quote = invoice.items.get()
    manual = InvoiceItem.objects.create(invoice=invoice, description="Упаковка", quantity=1)
    qi = from_quote.source_quote_item
    QuoteItem.objects.filter(pk=qi.pk).update(unit="шт", unit_code="H87")
    InvoiceItem.objects.filter(pk__in=[from_quote.pk, manual.pk]).update(product=None, unit="", unit_code="")

    with override_settings(OWN_COMPANY_ID=world["seller"].pk):
        migration.forwards(apps, None)

    from_quote.refresh_from_db()
    manual.refresh_from_db()
    assert from_quote.product_id == qi.product_id and from_quote.unit_code == "H87"
    assert manual.product is not None and manual.product.name == "Упаковка"
    assert manual.product.status.code == "DRAFT" and manual.product.source_deal_id == world["deal"].pk
    assert not InvoiceItem.objects.filter(product__isnull=True).exists()
