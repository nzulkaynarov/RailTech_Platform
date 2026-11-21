"""СЦ-8: отгрузка со склада переносит статус на строки поставки проекта — в БД и в карточке проекта.

Факт, из которого строка «Отгружено»: товар строки ушёл со склада (`ShipmentLine`) или исполнение сделки «Отгружено».
"""

import pytest
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
