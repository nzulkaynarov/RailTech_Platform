"""СЦ-9: ручные отметки «В пути» и «Доставлено» не предлагаются и не принимаются, пока товар с карточкой каталога не
отгружен со склада; товар без карточки каталога сохраняет ручной путь (иначе ему нечем стать «Отгружено»)."""

import pytest
from inventory.tests.support import api, make_deal
from sales.services import delivery_progress
from sales.services.delivery_progress import DeliveryMark

from crm.constants import FulfillmentStatusCode
from crm.models import Fulfillment, QuoteItem

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


def _today() -> str:
    from django.utils import timezone

    return timezone.localdate().isoformat()


def _mark(world, deal, action="delivered"):
    return delivery_progress.mark_delivery(deal.pk, world["supply"], DeliveryMark(action=action, on_date=_today()))


def _ship_all(world, deal, item, quantity):
    api(world["supply"]).post(
        f"{STOCK}adjustments/", {"product_id": item.product_id, "quantity": quantity, "cell": "A-01"}, format="json"
    )
    reservation = api(world["supply"]).post(
        f"{STOCK}reservations/", {"deal_id": deal.pk, "quote_item_id": item.pk, "quantity": quantity}, format="json"
    )
    assert reservation.status_code == 201, reservation.json()
    shipped = api(world["shipper"]).post(
        f"{STOCK}shipments/",
        {"deal_id": deal.pk, "lines": [{"reservation_id": reservation.json()["id"], "quantity": quantity}]},
        format="json",
    )
    assert shipped.status_code == 201, shipped.json()


def test_marks_are_not_offered_and_refused_while_catalog_goods_are_on_the_shelf(world):
    deal, _quote, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    fulfillment = Fulfillment.objects.get(deal=deal)
    assert delivery_progress.available_actions(fulfillment, world["supply"]) == []
    for action in ("in_transit", "delivered"):
        result, error = _mark(world, deal, action)
        assert (result, error) == (None, "GOODS_NOT_SHIPPED")
    assert delivery_progress.HTTP_STATUS["GOODS_NOT_SHIPPED"] == 409
    fulfillment.refresh_from_db()
    assert fulfillment.status.code == FulfillmentStatusCode.PENDING


def test_marks_open_after_the_warehouse_shipment(world):
    deal, _quote, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    _ship_all(world, deal, item, 4)
    fulfillment = Fulfillment.objects.get(deal=deal)
    assert fulfillment.status.code == FulfillmentStatusCode.SHIPPED
    assert delivery_progress.available_actions(fulfillment, world["supply"]) == ["in_transit", "delivered"]
    result, error = _mark(world, deal)
    assert error is None and result.status.code == FulfillmentStatusCode.DELIVERED


def test_goods_without_a_catalog_card_keep_the_manual_path(world):
    deal, _quote, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    QuoteItem.objects.filter(pk=item.pk).update(product=None)
    fulfillment = Fulfillment.objects.get(deal=deal)
    assert delivery_progress.available_actions(fulfillment, world["supply"]) == ["in_transit", "delivered"]
    result, error = _mark(world, deal)
    assert error is None and result.status.code == FulfillmentStatusCode.DELIVERED
