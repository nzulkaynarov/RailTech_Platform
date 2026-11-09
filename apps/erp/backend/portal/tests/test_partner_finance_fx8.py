"""FX-8: оборот и оценка партнёра — точные числа по формулам `docs/systems/erp/partner-scorecard.md`. Компании вымышленные."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from portal.tests.partner_world import client_for
from portal.tests.test_partner_orders_flow import make_order, make_rfq
from supply.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    OrderStatus,
    PriceRequest,
    PriceRequestStatus,
    SupplierOrderShipmentNotice,
)

from catalog.models import SupplierOffer
from master_data.models import Currency

pytestmark = pytest.mark.django_db

URL = "/api/portal/v1/partner/finance"
TASHKENT = ZoneInfo("Asia/Tashkent")


def receive(order, quantity, at):
    line = order.lines.get()
    receipt = GoodsReceipt.objects.create(order=order, supplier_doc="N-1")
    GoodsReceiptLine.objects.create(receipt=receipt, order_line=line, quantity=quantity)
    GoodsReceipt.objects.filter(pk=receipt.pk).update(received_at=at)
    line.received_quantity += quantity
    line.save(update_fields=["received_quantity"])


def local_noon(day):
    return datetime(day.year, day.month, day.day, 12, tzinfo=TASHKENT)


def summary(world, **params):
    response = client_for(world["a_contact"]).get(URL, params)
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def world(partner_world):
    return partner_world


def test_no_data_is_null_not_a_hundred(world):
    SupplierOffer.objects.filter(supplier=world["a"]).update(is_active=False)
    card = summary(world)["scorecard"]
    assert card["otif_rate"] is None
    assert card["rfq_response_rate"] is None
    assert card["rfq_avg_response_hours"] is None
    assert card["price_freshness_rate"] is None
    assert card["otif_orders_count"] == 0


def test_drafts_are_not_turnover(world):
    make_order(world["a"], OrderStatus.DRAFT)
    data = summary(world)
    assert data["balances"] == []
    assert data["settlements"] == []
    assert data["settlements_total"] == 0


def test_in_transit_counts_only_reported_shipments(world):
    uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум"})
    make_order(world["a"], OrderStatus.SENT, currency=uzs)
    make_order(world["a"], OrderStatus.CONFIRMED, currency=uzs)
    shipped = make_order(world["a"], OrderStatus.CONFIRMED, currency=uzs)
    SupplierOrderShipmentNotice.objects.create(order=shipped, supplier_doc="N-7")
    balance = summary(world)["balances"][0]
    assert balance["ordered_total"] == "150.00"
    assert balance["in_transit_total"] == "50.00"


def test_order_without_currency_is_not_shown_as_rub(world):
    make_order(world["a"], OrderStatus.SENT)
    data = summary(world)
    assert data["balances"][0]["currency"] is None
    assert data["settlements"][0]["currency"] is None


def test_otif_exact_rate(world):
    today = timezone.localdate()
    due = today - timedelta(days=5)
    on_time = make_order(world["a"], OrderStatus.RECEIVED, expected=due)
    receive(on_time, 10, local_noon(due))
    late = make_order(world["a"], OrderStatus.RECEIVED, expected=due)
    receive(late, 10, local_noon(due + timedelta(days=1)))
    split = make_order(world["a"], OrderStatus.RECEIVED, expected=due)
    receive(split, 6, local_noon(due))
    receive(split, 4, local_noon(due + timedelta(days=2)))
    make_order(world["a"], OrderStatus.CONFIRMED, expected=due)  # срок прошёл, не принят
    make_order(world["a"], OrderStatus.CONFIRMED, expected=today + timedelta(days=3))  # срок не наступил
    make_order(world["a"], OrderStatus.SENT, expected=due)  # партнёр срок не обещал
    make_order(world["a"], OrderStatus.RECEIVED)  # без срока мерить нечего
    card = summary(world)["scorecard"]
    assert card["otif_orders_count"] == 4
    assert card["otif_rate"] == 25.0


def test_otif_day_boundary_is_tashkent(world):
    due = timezone.localdate() - timedelta(days=5)
    order = make_order(world["a"], OrderStatus.RECEIVED, expected=due)
    # 00:30 следующего дня по Ташкенту — в UTC это ещё день срока: считать надо по Ташкенту
    receive(order, 10, datetime(due.year, due.month, due.day, 23, 30, tzinfo=TASHKENT) + timedelta(hours=1))
    card = summary(world)["scorecard"]
    assert card["otif_rate"] == 0.0


def test_rfq_rate_excludes_undelivered_and_measures_speed(world):
    answered = make_rfq(world["a"])
    now = timezone.now()
    PriceRequest.objects.filter(pk=answered.pk).update(requested_at=now - timedelta(hours=10), answered_at=now)
    second = make_rfq(world["a"])
    PriceRequest.objects.filter(pk=second.pk).update(requested_at=now - timedelta(hours=20), answered_at=now)
    make_rfq(world["a"])
    make_rfq(world["a"])
    make_rfq(world["a"], status=PriceRequestStatus.FAILED)
    card = summary(world)["scorecard"]
    assert card["total_rfqs_count"] == 4
    assert card["rfq_response_rate"] == 50.0
    assert card["rfq_avg_response_hours"] == 15.0


def test_settlements_are_paginated_totals_are_not(world):
    uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум"})
    for _ in range(3):
        make_order(world["a"], OrderStatus.SENT, currency=uzs)
    data = summary(world, page=2, page_size=2)
    assert len(data["settlements"]) == 1
    assert data["settlements_total"] == 3
    assert data["balances"][0]["orders_count"] == 3
    assert data["balances"][0]["ordered_total"] == "150.00"
