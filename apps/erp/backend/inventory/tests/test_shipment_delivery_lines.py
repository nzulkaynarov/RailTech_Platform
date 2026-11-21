"""СЦ-8: отгрузка со склада переносит статус на строки поставки проекта — в БД и в карточке проекта.

Факт, из которого строка «Отгружено»: товар строки ушёл со склада (`ShipmentLine`) или исполнение сделки «Отгружено».
"""

from datetime import datetime, timedelta

import pytest
from django.utils import timezone
from inventory.models import Shipment
from inventory.tests.support import api, make_deal
from sales.models import DeliveryLine, DeliveryLineStatus
from sales.services import delivery_lines, delivery_progress
from sales.services.delivery_progress import DeliveryMark

from crm.constants import FulfillmentStatusCode
from crm.models import Fulfillment, QuoteItem
from crm.services.projects import project_card

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


def _ship(world, deal, item, quantity, shipped_quantity=None):
    """Принять на склад `quantity`, зарезервировать и отгрузить `shipped_quantity` (по умолчанию всё)."""
    api(world["supply"]).post(
        f"{STOCK}adjustments/", {"product_id": item.product_id, "quantity": quantity, "cell": "A-01"}, format="json"
    )
    reservation = api(world["supply"]).post(
        f"{STOCK}reservations/", {"deal_id": deal.pk, "quote_item_id": item.pk, "quantity": quantity}, format="json"
    )
    assert reservation.status_code == 201, reservation.json()
    shipped = api(world["shipper"]).post(
        f"{STOCK}shipments/",
        {
            "deal_id": deal.pk,
            "lines": [{"reservation_id": reservation.json()["id"], "quantity": shipped_quantity or quantity}],
        },
        format="json",
    )
    assert shipped.status_code == 201, shipped.json()


def _card_statuses(deal, user):
    return {line["title"]: line["status"] for line in project_card(deal, user)["delivery_lines"]}


def test_shipment_creates_missing_lines_as_shipped_in_db_and_card(world):
    deal, _quote, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    assert not DeliveryLine.objects.filter(deal=deal).exists()
    _ship(world, deal, item, 4)
    line = DeliveryLine.objects.get(deal=deal)
    assert line.status == DeliveryLineStatus.SHIPPED and line.shipped_at is not None
    assert _card_statuses(deal, world["supply"]) == {world["rail"].name: "shipped"}


def test_shipment_moves_existing_assembling_lines_to_shipped(world):
    deal, _quote, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    delivery_lines.sync_delivery_lines(Fulfillment.objects.filter(deal=deal).select_related("status"))
    assert DeliveryLine.objects.get(deal=deal).status == DeliveryLineStatus.ASSEMBLING
    _ship(world, deal, item, 4)
    assert DeliveryLine.objects.get(deal=deal).status == DeliveryLineStatus.SHIPPED
    assert _card_statuses(deal, world["supply"]) == {world["rail"].name: "shipped"}


def test_partial_shipment_marks_only_the_shipped_lines(world):
    deal, _quote, (rail, bolt) = make_deal(world, [(world["rail"], 4), (world["bolt"], 10)], approved=True, signed=True)
    _ship(world, deal, bolt, 10)
    fulfillment = Fulfillment.objects.get(deal=deal)
    assert fulfillment.status.code == FulfillmentStatusCode.PENDING
    assert _card_statuses(deal, world["supply"]) == {
        world["rail"].name: "assembling",
        world["bolt"].name: "shipped",
    }
    # Часть количества строки — ещё не «Отгружено».
    _ship(world, deal, rail, 4, shipped_quantity=1)
    assert DeliveryLine.objects.get(quote_item=rail).status == DeliveryLineStatus.ASSEMBLING


def test_goods_without_a_catalog_card_keep_the_manual_path(world):
    deal, _quote, (item,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    QuoteItem.objects.filter(pk=item.pk).update(product=None)
    result, error = delivery_progress.mark_delivery(
        deal.pk, world["supply"], DeliveryMark(action="delivered", on_date="2026-11-20")
    )
    assert error is None
    assert DeliveryLine.objects.get(deal=deal).status == DeliveryLineStatus.DELIVERED


def test_lines_shipped_on_different_days_keep_their_own_date(world):
    deal, _quote, (rail, bolt) = make_deal(world, [(world["rail"], 4), (world["bolt"], 10)], approved=True, signed=True)
    _ship(world, deal, bolt, 10)
    earlier = timezone.now() - timedelta(days=5)
    Shipment.objects.filter(deal=deal).update(shipped_at=earlier)
    _ship(world, deal, rail, 4)  # the last goods leave: the fulfillment itself becomes SHIPPED now
    assert Fulfillment.objects.get(deal=deal).status.code == FulfillmentStatusCode.SHIPPED
    bolt_line = DeliveryLine.objects.get(quote_item=bolt)
    rail_line = DeliveryLine.objects.get(quote_item=rail)
    assert bolt_line.status == rail_line.status == DeliveryLineStatus.SHIPPED
    assert bolt_line.shipped_at == earlier
    assert rail_line.shipped_at > earlier + timedelta(days=4)
    body = api(world["supply"]).get(f"/api/v1/crm/projects/{deal.pk}/").json()
    card = {row["title"]: row["shipped_at"] for row in body["delivery_lines"]}
    assert datetime.fromisoformat(card[world["bolt"].name]) == earlier


@pytest.mark.parametrize(
    ("status", "line_status"),
    [("SHIPPED", "shipped"), ("IN_TRANSIT", "in_transit")],
)
def test_manual_update_status_creates_lines_and_shows_them_in_the_project_card(world, status, line_status):
    deal, _quote, _items = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    assert not DeliveryLine.objects.filter(deal=deal).exists()
    response = api(world["supply"]).post(
        "/api/v1/crm/fulfillments/update-status/",
        {"deal_id": deal.pk, "status": status, "tracking_number": "TRK-1"},
        format="json",
    )
    assert response.status_code == 200, response.content
    line = DeliveryLine.objects.get(deal=deal)
    assert line.status == line_status and line.tracking == "TRK-1"
    card = api(world["supply"]).get(f"/api/v1/crm/projects/{deal.pk}/")
    assert card.status_code == 200, card.content
    lines = card.json()["delivery_lines"]
    assert [row["status"] for row in lines] == [line_status]
