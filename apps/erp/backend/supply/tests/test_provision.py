"""D26G-1 и D26G-8 (гейт D2-6): принятие КП → резерв склада и черновик заказа поставщику на дефицит (SPEC-v3 §3.1 ш. 6).

* Принятие КП резервирует свободный остаток под строки-товары и заводит черновик ЗП на дефицит у поставщика строки;
  строка без предложения поставщика — запись «Дефицит без поставщика», заказа нет. Повтор не создаёт дублей.
* Выигранная заявка (`CLOSED_WON`, договор подписан) открыта для резерва и приёмки под проект; выполненная — нет.
* Приёмка заказа на дефицит закрепляет товар за резервом проекта — отгрузка идёт по резервам.
* Отклонение КП и отмена проекта снимают резервы и отменяют черновики под заявку.
* Срок строки в КП — максимум из срока «со склада» и срока поставщика на дефицит; нет данных — «срок уточняется».
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core import mail
from inventory.models import Reservation, ReservationStatus
from inventory.services import stock
from inventory.tests.support import api, make_deal
from inventory.tests.test_stock import _adjust, _reserve
from supply.models import OrderStatus, SupplierOrder
from supply.services.provision import provision_accepted_quote

from catalog.models import SupplierOffer
from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import ActivityLog, Contract, ContractStatus, DealStage, QuoteStatus
from master_data.models import Currency

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


@pytest.fixture(autouse=True)
def locmem_mail(settings):
    channel = {
        "backend": "django.core.mail.backends.locmem.EmailBackend",
        "host": "",
        "port": 25,
        "username": "",
        "password": "",
        "use_tls": False,
        "from_email": "erp@demo.example",
    }
    settings.EMAIL_CHANNELS = {name: dict(channel) for name in ("transactional", "marketing", "system")}
    mail.outbox.clear()


def _offer(world, product, *, order_lead=10, in_stock_lead=0, stock_quantity=0, price="900.00", supplier="vendor"):
    return SupplierOffer.objects.create(
        product=product,
        supplier=world[supplier],
        base_price=Decimal(price),
        currency=Currency.objects.get(code="UZS"),
        order_lead_time_days=order_lead,
        in_stock_lead_time_days=in_stock_lead,
        stock_quantity=stock_quantity,
        is_active=True,
    )


def _stage(deal, code):
    deal.stage = DealStage.objects.get(code=code)
    deal.save(update_fields=["stage"])


def _sent_quote(world, goods):
    deal, quote, items = make_deal(world, goods)
    _stage(deal, DealStageCode.QUOTE_SENT)
    quote.status = QuoteStatus.objects.get(code=QuoteStatusCode.SENT)
    quote.save(update_fields=["status"])
    return deal, quote, items


def _accept(quote):
    from crm.services.quotes.lifecycle_accept import perform_quote_acceptance

    return perform_quote_acceptance(quote.pk, contact_email="buyer@client.test")


# ── принятие КП ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_acceptance_reserves_stock_and_drafts_an_order_for_the_shortage(world):
    _adjust(world, world["rail"], 15)
    _offer(world, world["rail"], order_lead=10)
    deal, quote, (rail, bolt) = _sent_quote(world, [(world["rail"], 40), (world["bolt"], 5)])

    _accept(quote)

    deal.refresh_from_db()
    assert deal.stage.code == DealStageCode.CONTRACT_SIGNED
    reservation = Reservation.objects.get(quote_item=rail, status=ReservationStatus.ACTIVE)
    assert reservation.quantity == 15, "резерв — весь свободный остаток, не больше строки"
    assert not Reservation.objects.filter(quote_item=bolt).exists(), "болта на складе нет"
    (order,) = SupplierOrder.objects.all()
    assert order.status == OrderStatus.DRAFT and order.supplier == world["vendor"]
    (line,) = order.lines.all()
    assert (line.quote_item_id, line.deal_id, line.quantity) == (rail.pk, deal.pk, 25), "дефицит = 40 − 15"
    assert line.unit_price == Decimal("900.00"), "цена — из предложения поставщика"
    events = set(ActivityLog.objects.filter(deal=deal).values_list("event_code", flat=True))
    assert {"stock.reserved_on_accept", "supply.draft_on_accept", "supply.shortage_without_supplier"} <= events


def test_provisioning_is_idempotent(world):
    _adjust(world, world["rail"], 15)
    _offer(world, world["rail"])
    _deal, quote, (rail,) = _sent_quote(world, [(world["rail"], 40)])
    _accept(quote)

    again = provision_accepted_quote(quote)

    assert again["orders"] == [] and again["shortage"] == {rail.pk: 25}
    assert Reservation.objects.filter(quote_item=rail).count() == 1
    assert Reservation.objects.get(quote_item=rail).quantity == 15
    assert SupplierOrder.objects.count() == 1, "уже заказано в живом черновике — второго нет"


def test_manual_reservation_before_acceptance_counts(world):
    _adjust(world, world["rail"], 50)
    deal, quote, (rail,) = _sent_quote(world, [(world["rail"], 40)])
    _stage(deal, DealStageCode.CALCULATING)
    assert _reserve(world, deal, rail, 10).status_code == 201
    _stage(deal, DealStageCode.QUOTE_SENT)

    _accept(quote)

    assert Reservation.objects.get(quote_item=rail, status=ReservationStatus.ACTIVE).quantity == 40
    assert not SupplierOrder.objects.exists(), "склада хватило — заказ не нужен"


def test_shortage_without_a_supplier_offer_is_noted_not_ordered(world):
    deal, quote, (bolt,) = _sent_quote(world, [(world["bolt"], 5)])

    summary = provision_accepted_quote(quote)

    assert summary["without_supplier"] == [bolt.pk] and summary["orders"] == []
    assert not SupplierOrder.objects.exists()
    log = ActivityLog.objects.get(deal=deal, event_code="supply.shortage_without_supplier")
    assert "Болт путевой М22: 5" in log.detail


# ── выигранная заявка открыта для исполнения ────────────────────────────────────────────────────────────────────────


def test_a_won_deal_takes_manual_reservations_until_it_is_done(world, monkeypatch):
    _adjust(world, world["rail"], 10)
    deal, _q, (rail,) = make_deal(world, [(world["rail"], 4)], approved=True, signed=True)
    _stage(deal, DealStageCode.CLOSED_WON)
    response = _reserve(world, deal, rail, 4)
    assert response.status_code == 201, response.json()

    monkeypatch.setattr("crm.services.deal_documents.deal_execution_is_complete", lambda _deal: True)
    done = _reserve(world, deal, rail, 3)
    assert done.status_code == 409 and done.json() == {"detail": "DEAL_CLOSED"}, "выполненная заявка закрыта"


def test_receipt_of_the_shortage_order_lands_in_the_project_reservation_and_ships(world):
    _adjust(world, world["rail"], 15)
    _offer(world, world["rail"])
    deal, quote, (rail,) = _sent_quote(world, [(world["rail"], 40)])
    _accept(quote)
    # договор подписан: заявка CLOSED_WON, исполнение заведено
    Contract.objects.filter(deal=deal).update(status=ContractStatus.objects.get_or_create(code="SIGNED")[0])
    from crm.services.fulfillment import ensure_fulfillment

    ensure_fulfillment(deal)
    _stage(deal, DealStageCode.CLOSED_WON)

    order = SupplierOrder.objects.get()
    supply = api(world["supply"])
    assert supply.post(f"{STOCK}orders/{order.pk}/send/", {}, format="json").status_code == 200
    confirmed = supply.post(f"{STOCK}orders/{order.pk}/confirm/", {"expected_date": "2030-01-10"}, format="json")
    assert confirmed.status_code == 200, confirmed.json()
    line = order.lines.get()
    received = supply.post(
        f"{STOCK}orders/{order.pk}/receipts/", {"lines": [{"order_line_id": line.pk, "quantity": 25}]}, format="json"
    )
    assert received.status_code == 200, received.json()
    reservation = Reservation.objects.get(quote_item=rail, status=ReservationStatus.ACTIVE)
    assert reservation.quantity == 40, "принятое закрепилось за резервом проекта"

    shipped = api(world["supply"]).post(
        f"{STOCK}shipments/",
        {"deal_id": deal.pk, "lines": [{"reservation_id": reservation.pk, "quantity": 40}]},
        format="json",
    )
    assert shipped.status_code == 201, shipped.json()


# ── отклонение и отмена ─────────────────────────────────────────────────────────────────────────────────────────────


def test_rejection_releases_reservations_and_cancels_project_drafts(world):
    from crm.services.quotes.lifecycle_accept import perform_quote_rejection

    _adjust(world, world["rail"], 15)
    _offer(world, world["rail"])
    deal, quote, (rail,) = _sent_quote(world, [(world["rail"], 40)])
    _stage(deal, DealStageCode.CALCULATING)
    assert _reserve(world, deal, rail, 15).status_code == 201
    created = api(world["supply"]).post(
        f"{STOCK}orders/from-deal/", {"deal_id": deal.pk, "supplier_id": world["vendor"].pk}, format="json"
    )
    assert created.status_code == 201
    _stage(deal, DealStageCode.QUOTE_SENT)

    perform_quote_rejection(quote.pk, contact_email="buyer@client.test", reason="Дорого")

    assert not Reservation.objects.filter(deal=deal, status=ReservationStatus.ACTIVE).exists()
    order = SupplierOrder.objects.get()
    assert order.status == OrderStatus.CANCELLED and "отклонено" in order.cancel_reason
    row = api(world["supply"]).get(f"{STOCK}balances/", {"q": "стрелочный"}).json()["results"][0]
    assert (row["reserved"], row["free"]) == (0, 15)


def test_release_for_deal_keeps_shipped_part_sent_orders_and_is_repeatable(world):
    _adjust(world, world["rail"], 10)
    deal, _q, (rail,) = make_deal(world, [(world["rail"], 6)], approved=True, signed=True)
    reservation_id = _reserve(world, deal, rail, 6).json()["id"]
    shipped = api(world["supply"]).post(
        f"{STOCK}shipments/",
        {"deal_id": deal.pk, "lines": [{"reservation_id": reservation_id, "quantity": 2}]},
        format="json",
    )
    assert shipped.status_code == 201
    sent = (
        api(world["supply"])
        .post(
            f"{STOCK}orders/",
            {
                "supplier_id": world["vendor"].pk,
                "lines": [{"product_id": world["rail"].pk, "quantity": 3, "deal_id": deal.pk}],
            },
            format="json",
        )
        .json()["id"]
    )
    assert api(world["supply"]).post(f"{STOCK}orders/{sent}/send/", {}, format="json").status_code == 200

    assert stock.release_for_deal(deal, reason="Проект отменён") == 1
    reservation = Reservation.objects.get(pk=reservation_id)
    assert (reservation.status, reservation.quantity) == (ReservationStatus.FULFILLED, 2), "отгруженное — факт"
    assert SupplierOrder.objects.get(pk=sent).status == OrderStatus.SENT, "отправленный заказ не отменяется"
    assert stock.release_for_deal(deal) == 0, "повтор ничего не меняет"


def test_lost_deal_cancels_its_drafts(world):
    from crm.services.deals import transition_deal_stage

    deal, _q, (rail,) = make_deal(world, [(world["rail"], 4)])
    api(world["supply"]).post(
        f"{STOCK}orders/from-deal/", {"deal_id": deal.pk, "supplier_id": world["vendor"].pk}, format="json"
    )
    _deal, err = transition_deal_stage(deal, DealStageCode.CLOSED_LOST, actor=world["supply"])
    assert err is None
    assert SupplierOrder.objects.get().status == OrderStatus.CANCELLED


# ── срок КП (D26G-8) ────────────────────────────────────────────────────────────────────────────────────────────────


def _leads(world, quote):
    from crm.services.calculation import _billable, apply_delivery_leads

    pending = apply_delivery_leads(quote, _billable(quote))
    quote.refresh_from_db()
    return pending, {item.product_id: item.lead_time_days for item in quote.items.all()}


def _with_lead(items, days):
    for item in items:
        item.lead_time_days = days
        item.save(skip_recalculate=True)


def test_lead_of_a_short_line_takes_the_supplier_lead(world):
    _adjust(world, world["rail"], 15)
    _adjust(world, world["bolt"], 100)
    _offer(world, world["rail"], order_lead=10)
    _deal, quote, items = make_deal(world, [(world["rail"], 40), (world["bolt"], 50)])
    _with_lead(items, 2)  # срок «со склада» из своего предложения

    pending, leads = _leads(world, quote)

    assert pending == []
    assert leads == {world["rail"].pk: 10, world["bolt"].pk: 2}, "дефицит — срок поставщика, склад покрывает — 2 дн."
    assert quote.effective_delivery_lead_time_days == 10
    from crm.services.document_blocks import _contract_delivery_terms

    assert _contract_delivery_terms(quote).startswith("в срок до 10 календарных дней")


def test_supplier_stock_covering_the_shortage_gives_its_stock_lead(world):
    _offer(world, world["rail"], order_lead=30, in_stock_lead=5, stock_quantity=100)
    _deal, quote, items = make_deal(world, [(world["rail"], 40)])
    _with_lead(items, 0)

    _pending, leads = _leads(world, quote)

    assert leads[world["rail"].pk] == 5


def test_unknown_supplier_lead_is_honest(world):
    from crm.services.calculation import LEAD_PENDING_NOTE
    from crm.services.document_blocks import _contract_delivery_terms
    from crm.services.documents.projection import client_projection_items

    _adjust(world, world["rail"], 15)
    _deal, quote, items = make_deal(world, [(world["rail"], 40)])
    _with_lead(items, 0)

    pending, leads = _leads(world, quote)

    assert pending == [items[0].pk] and leads[world["rail"].pk] == 0
    assert (quote.delivery_lead_time_days, quote.delivery_note) == (0, LEAD_PENDING_NOTE)
    assert _contract_delivery_terms(quote).startswith("в сроки, согласованные Сторонами")
    assert client_projection_items(quote)[0]["lead_pending"] is True

    # снабженец нашёл поставщика — при повторном «Расчёт готов» пометка снимается
    _offer(world, world["rail"], order_lead=12)
    pending, leads = _leads(world, quote)
    assert pending == [] and leads[world["rail"].pk] == 12
    assert (quote.delivery_lead_time_days, quote.delivery_note) == (None, "")


def test_lead_entered_by_supply_counts_as_data(world):
    _deal, quote, items = make_deal(world, [(world["rail"], 40)])
    _with_lead(items, 21)  # своего предложения нет: срок ввёл снабженец

    pending, leads = _leads(world, quote)

    assert pending == [] and leads[world["rail"].pk] == 21
