"""FX-7: заказы и запросы цен партнёра — переходы, срок, ответы, уведомления снабжения, внутренние данные (ADR-0022, K2).

Негативный тест на каждый переход; партнёр не меняет срок заказа и не видит внутренних заметок. Компании вымышленные.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from inventory.tests.support import make_deal
from parties.models import CompanyRelationship, Contact, RelationshipRole
from portal.error_codes import ERROR_CODES
from portal.services import partner_orders
from portal.tests.partner_world import client_for, make_offer
from supply import models as supply_models
from supply.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    OrderLogKind,
    OrderStatus,
    PriceRequest,
    PriceRequestLine,
    PriceRequestStatus,
    SupplierOrder,
    SupplierOrderLine,
    SupplierOrderLog,
)
from supply.services import orders as staff_orders

from catalog.models import SupplierOffer
from master_data.models import Currency
from notifications.models import Notification

pytestmark = pytest.mark.django_db

PREFIX = "/api/portal/v1/partner"
SECRET_NOTE = "Внутренняя заметка: поставщик ненадёжен"


def today():
    return timezone.localdate()


_seq = iter(range(100, 10_000))


def make_order(supplier, status=OrderStatus.SENT, *, expected=None, currency=None, created_by=None, note=""):
    seq = next(_seq)
    order = SupplierOrder.objects.create(
        number=f"ЗП-2026-{seq}",
        number_year=2026,
        number_seq=seq,
        supplier=supplier,
        status=status,
        expected_date=expected,
        currency=currency,
        created_by=created_by,
        note=note,
    )
    SupplierOrderLine.objects.create(
        order=order, position=1, name="Болт", article="B-1", unit="шт", quantity=10, unit_price=Decimal("5.00")
    )
    return order


def make_rfq(supplier, *, status=PriceRequestStatus.SENT, requested_by=None, deal=None, answered=False):
    return PriceRequest.objects.create(
        supplier=supplier,
        to_email="sales@plant.example",
        subject="Запрос цен",
        status=status,
        requested_by=requested_by,
        deal=deal,
        answered_at=timezone.now() if answered else None,
        answer_note="Первый ответ" if answered else "",
    )


def post(client, path, body=None):
    return client.post(f"{PREFIX}/{path}", body if body is not None else {}, format="json")


def in_days(days):
    return (today() + timedelta(days=days)).isoformat()


# ── Черновики ─────────────────────────────────────────────────────────────────────────────────────────


def test_partner_does_not_see_drafts(partner_world):
    w = partner_world
    draft = make_order(w["a"], OrderStatus.DRAFT)
    sent = make_order(w["a"], OrderStatus.SENT)
    client = w["client_a"]

    body = client.get(f"{PREFIX}/orders").json()
    assert [item["id"] for item in body["items"]] == [sent.pk]
    assert body["total"] == 1 and body["counts"]["all"] == 1
    assert client.get(f"{PREFIX}/orders?status=draft").json()["items"] == []
    assert client.get(f"{PREFIX}/orders/{draft.pk}").status_code == 404
    assert post(client, f"orders/{draft.pk}/confirm", {"expected_date": in_days(5)}).status_code == 404
    assert post(client, f"orders/{draft.pk}/ship", {"supplier_doc": "ТТН-1"}).status_code == 404
    assert post(client, f"orders/{draft.pk}/date-change", {"requested_date": in_days(5)}).status_code == 404
    draft.refresh_from_db()
    assert draft.status == OrderStatus.DRAFT


# ── Подтверждение ─────────────────────────────────────────────────────────────────────────────────────


def test_confirm_needs_a_date(partner_world):
    w = partner_world
    order = make_order(w["a"])
    for body in ({}, {"expected_date": None}, {"expected_date": "не дата"}, {"expected_date": in_days(-1)}):
        response = post(w["client_a"], f"orders/{order.pk}/confirm", body)
        assert response.status_code == 422, body
        assert response.json() == {"detail": "VALIDATION_ERROR"}
    order.refresh_from_db()
    assert order.status == OrderStatus.SENT and order.confirmed_at is None


@pytest.mark.parametrize("status", [OrderStatus.CONFIRMED, OrderStatus.RECEIVED, OrderStatus.CANCELLED])
def test_only_a_sent_order_can_be_confirmed(partner_world, status):
    w = partner_world
    agreed = today() + timedelta(days=10)
    order = make_order(w["a"], status, expected=agreed)
    response = post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(30)})
    assert response.status_code == 409
    assert response.json() == {"detail": "TRANSITION_NOT_ALLOWED"}
    order.refresh_from_db()
    assert order.status == status and order.expected_date == agreed and order.confirmed_at is None


def test_repeat_confirmation_changes_nothing(partner_world):
    w = partner_world
    order = make_order(w["a"], expected=today() + timedelta(days=10))
    assert post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(10)}).status_code == 200
    order.refresh_from_db()
    first_confirmed_at = order.confirmed_at
    assert post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(10)}).status_code == 409
    order.refresh_from_db()
    assert order.confirmed_at == first_confirmed_at
    assert SupplierOrderLog.objects.filter(order=order, kind=OrderLogKind.CONFIRMED).count() == 1


def test_order_without_a_date_takes_the_partners_date(partner_world):
    w = partner_world
    order = make_order(w["a"])
    response = post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(12)})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed" and body["expected_date"] == in_days(12) and body["date_change"] is None


# ── Перенос срока: запрос сотруднику, срок не двигается ────────────────────────────────────────────────


def test_confirm_with_another_date_keeps_the_agreed_date_and_asks_staff(partner_world):
    w = partner_world
    agreed = today() + timedelta(days=10)
    order = make_order(w["a"], expected=agreed, created_by=w["staff"])
    response = post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(30)})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["expected_date"] == agreed.isoformat(), "срок для OTIF партнёр не сдвигает"
    assert body["date_change"]["requested_date"] == in_days(30)
    order.refresh_from_db()
    assert order.expected_date == agreed
    assert Notification.objects.filter(user=w["staff"], event_code="supplier_order.partner_date_change").exists()


def test_confirm_with_the_agreed_date_is_not_a_request(partner_world):
    w = partner_world
    order = make_order(w["a"], expected=today() + timedelta(days=10))
    body = post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(10)}).json()
    assert body["date_change"] is None


def test_date_change_request_keeps_the_deadline(partner_world):
    w = partner_world
    agreed = today() + timedelta(days=10)
    order = make_order(w["a"], OrderStatus.CONFIRMED, expected=agreed, created_by=w["staff"])
    response = post(
        w["client_a"], f"orders/{order.pk}/date-change", {"requested_date": in_days(20), "reason": "Задержка сырья"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["expected_date"] == agreed.isoformat()
    assert body["date_change"]["requested_date"] == in_days(20)
    assert body["date_change"]["reason"] == "Задержка сырья"
    order.refresh_from_db()
    assert order.expected_date == agreed
    assert Notification.objects.filter(user=w["staff"], event_code="supplier_order.partner_date_change").count() == 1


def test_same_date_change_again_does_not_notify_twice(partner_world):
    w = partner_world
    order = make_order(w["a"], OrderStatus.CONFIRMED, expected=today() + timedelta(days=10), created_by=w["staff"])
    for _ in range(2):
        assert post(w["client_a"], f"orders/{order.pk}/date-change", {"requested_date": in_days(20)}).status_code == 200
    assert Notification.objects.filter(user=w["staff"], event_code="supplier_order.partner_date_change").count() == 1


def test_new_date_change_replaces_the_previous_one(partner_world):
    w = partner_world
    order = make_order(w["a"], OrderStatus.CONFIRMED, expected=today() + timedelta(days=10))
    post(w["client_a"], f"orders/{order.pk}/date-change", {"requested_date": in_days(20)})
    body = post(w["client_a"], f"orders/{order.pk}/date-change", {"requested_date": in_days(25)}).json()
    assert body["date_change"]["requested_date"] == in_days(25)


@pytest.mark.parametrize("status", [OrderStatus.SENT, OrderStatus.RECEIVED, OrderStatus.CANCELLED])
def test_date_change_only_for_a_confirmed_order(partner_world, status):
    w = partner_world
    order = make_order(w["a"], status, expected=today() + timedelta(days=10))
    response = post(w["client_a"], f"orders/{order.pk}/date-change", {"requested_date": in_days(20)})
    assert response.status_code == 409
    assert response.json() == {"detail": "ORDER_NOT_CONFIRMED"}
    order.refresh_from_db()
    assert order.partner_requested_date is None


def test_date_change_rejects_the_current_or_a_past_date(partner_world):
    w = partner_world
    order = make_order(w["a"], OrderStatus.CONFIRMED, expected=today() + timedelta(days=10))
    for date in (in_days(10), in_days(-1), "не дата"):
        response = post(w["client_a"], f"orders/{order.pk}/date-change", {"requested_date": date})
        assert response.status_code == 422, date


def test_staff_decision_closes_the_request(partner_world, seller_company):
    from accounts.constants import Permission
    from accounts.models import CompanyRole

    w = partner_world
    role = CompanyRole.objects.create(
        company=seller_company, name="Снабжение", permissions=[Permission.SUPPLY_MANAGE.value]
    )
    w["staff"].memberships.get(company=seller_company).company_roles.add(role)
    order = make_order(w["a"], OrderStatus.CONFIRMED, expected=today() + timedelta(days=10))
    post(w["client_a"], f"orders/{order.pk}/date-change", {"requested_date": in_days(20)})

    new_date = today() + timedelta(days=20)
    staff_orders.update_order(
        w["staff"], order.pk, staff_orders.OrderInput(expected_date=new_date, expected_given=True)
    )

    body = w["client_a"].get(f"{PREFIX}/orders/{order.pk}").json()
    assert body["expected_date"] == new_date.isoformat() and body["date_change"] is None


# ── Уведомление об отгрузке ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", [OrderStatus.SENT, OrderStatus.RECEIVED, OrderStatus.CANCELLED])
def test_shipment_notice_only_for_a_confirmed_order(partner_world, status):
    w = partner_world
    order = make_order(w["a"], status)
    response = post(w["client_a"], f"orders/{order.pk}/ship", {"supplier_doc": "ТТН-1"})
    assert response.status_code == 409
    assert response.json() == {"detail": "ORDER_NOT_CONFIRMED"}
    assert not supply_models.SupplierOrderShipmentNotice.objects.filter(order=order).exists()


def test_shipment_notice_is_not_duplicated(partner_world):
    w = partner_world
    order = make_order(w["a"], OrderStatus.CONFIRMED, created_by=w["staff"])
    assert post(w["client_a"], f"orders/{order.pk}/ship", {"supplier_doc": "ТТН-1"}).status_code == 200
    for doc in ("ТТН-1", " ттн-1 "):
        response = post(w["client_a"], f"orders/{order.pk}/ship", {"supplier_doc": doc})
        assert response.status_code == 409, doc
        assert response.json() == {"detail": "SHIPMENT_NOTICE_DUPLICATE"}
    assert supply_models.SupplierOrderShipmentNotice.objects.filter(order=order).count() == 1
    assert Notification.objects.filter(user=w["staff"], event_code="supplier_order.partner_shipped").count() == 1


def test_partial_shipment_with_another_document_is_allowed(partner_world):
    w = partner_world
    order = make_order(w["a"], OrderStatus.CONFIRMED)
    post(w["client_a"], f"orders/{order.pk}/ship", {"supplier_doc": "ТТН-1"})
    body = post(
        w["client_a"], f"orders/{order.pk}/ship", {"supplier_doc": "ТТН-2", "carrier": "Перевозчик", "note": "Партия 2"}
    ).json()
    assert [row["supplier_doc"] for row in body["shipment_notices"]] == ["ТТН-1", "ТТН-2"]
    assert body["shipment_notices"][1]["carrier"] == "Перевозчик"


# ── Ответ на запрос цен ───────────────────────────────────────────────────────────────────────────────


def test_second_answer_does_not_overwrite_the_first(partner_world):
    w = partner_world
    rfq = make_rfq(w["a"])
    assert post(w["client_a"], f"price-requests/{rfq.pk}/respond", {"answer_note": "Первый ответ"}).status_code == 200
    response = post(w["client_a"], f"price-requests/{rfq.pk}/respond", {"answer_note": "Другой ответ"})
    assert response.status_code == 409
    assert response.json() == {"detail": "ALREADY_ANSWERED"}
    rfq.refresh_from_db()
    assert rfq.answer_note == "Первый ответ"


def test_answer_to_an_undelivered_request_is_refused(partner_world):
    w = partner_world
    rfq = make_rfq(w["a"], status=PriceRequestStatus.FAILED)
    response = post(w["client_a"], f"price-requests/{rfq.pk}/respond", {"answer_note": "Ответ"})
    assert response.status_code == 409
    assert response.json() == {"detail": "REQUEST_NOT_SENT"}
    rfq.refresh_from_db()
    assert rfq.answered_at is None


def test_failed_filter_matches_the_contract(partner_world):
    w = partner_world
    failed = make_rfq(w["a"], status=PriceRequestStatus.FAILED)
    make_rfq(w["a"])
    response = w["client_a"].get(f"{PREFIX}/price-requests?status=failed")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [failed.pk]


def _rfq_on_product(w, product):
    deal, _quote, items = make_deal({"client": w["a"], "supply": w["staff"], "seller": w["own"]}, [(product, 3)])
    rfq = make_rfq(w["a"], requested_by=w["staff"], deal=deal)
    line = PriceRequestLine.objects.create(request=rfq, quote_item=items[0], name=product.name, quantity=3, unit="шт")
    return rfq, line


def test_answer_updates_the_supplier_price(partner_world):
    w = partner_world
    Currency.objects.get_or_create(code="USD", defaults={"name": "USD"})
    product = w["cards"]["published"]
    rfq, line = _rfq_on_product(w, product)
    until = today() + timedelta(days=30)

    response = post(
        w["client_a"],
        f"price-requests/{rfq.pk}/respond",
        {
            "answer_note": "Цена на партию",
            "currency": "USD",
            "valid_until": until.isoformat(),
            "lines": [{"id": line.pk, "unit_price": "77.50"}],
        },
    )

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["answer_currency"] == "USD" and body["lines"][0]["answer_price"] == "77.50"
    offer = SupplierOffer.objects.get(product=product, supplier=w["a"])
    assert offer.base_price == Decimal("77.50") and offer.currency.code == "USD"
    assert offer.source == SupplierOffer.Source.RFQ_REPLY and offer.valid_until == until
    assert offer.confirmed_by_contact == w["a_contact"]


def test_answer_creates_the_price_when_there_is_none(partner_world):
    w = partner_world
    Currency.objects.get_or_create(code="USD", defaults={"name": "USD"})
    product = w["cards"]["b_only"]
    assert not SupplierOffer.objects.filter(product=product, supplier=w["a"]).exists()
    rfq, line = _rfq_on_product(w, product)
    body = {"answer_note": "Есть", "currency": "USD", "lines": [{"id": line.pk, "unit_price": "10.00"}]}
    assert post(w["client_a"], f"price-requests/{rfq.pk}/respond", body).status_code == 200
    assert SupplierOffer.objects.get(product=product, supplier=w["a"]).base_price == Decimal("10.00")


def test_answer_does_not_touch_another_partners_price(partner_world):
    w = partner_world
    Currency.objects.get_or_create(code="USD", defaults={"name": "USD"})
    product = w["cards"]["shared"]
    rfq, line = _rfq_on_product(w, product)
    body = {"answer_note": "Есть", "currency": "USD", "lines": [{"id": line.pk, "unit_price": "1.00"}]}
    assert post(w["client_a"], f"price-requests/{rfq.pk}/respond", body).status_code == 200
    w["offers"]["shared_b"].refresh_from_db()
    assert w["offers"]["shared_b"].base_price == Decimal("9.99")


def test_answer_without_prices_keeps_the_price(partner_world):
    w = partner_world
    product = w["cards"]["published"]
    rfq, _line = _rfq_on_product(w, product)
    before = SupplierOffer.objects.get(product=product, supplier=w["a"]).base_price
    assert post(w["client_a"], f"price-requests/{rfq.pk}/respond", {"answer_note": "Нет в наличии"}).status_code == 200
    assert SupplierOffer.objects.get(product=product, supplier=w["a"]).base_price == before


def test_answer_price_on_a_line_without_a_product_is_kept_on_the_line(partner_world):
    w = partner_world
    Currency.objects.get_or_create(code="USD", defaults={"name": "USD"})
    rfq = make_rfq(w["a"])
    line = PriceRequestLine.objects.create(request=rfq, name="Без карточки", quantity=1, unit="шт")
    offers_before = SupplierOffer.objects.count()
    body = {"answer_note": "Есть", "currency": "USD", "lines": [{"id": line.pk, "unit_price": "5.00"}]}
    response = post(w["client_a"], f"price-requests/{rfq.pk}/respond", body)
    assert response.status_code == 200
    assert response.json()["lines"][0]["answer_price"] == "5.00"
    assert SupplierOffer.objects.count() == offers_before


@pytest.mark.parametrize(
    "patch",
    [
        {"lines": [{"id": 999_999, "unit_price": "5.00"}]},  # строка не этого запроса
        {"currency": None},  # цены без валюты
        {"currency": "XXX"},  # неизвестная валюта
        {"lines": "dup"},  # одна строка дважды
        {"lines": [{"id": "line", "unit_price": "0"}]},  # цена не больше нуля
        {"valid_until": "2000-01-01"},  # срок в прошлом
    ],
)
def test_bad_price_answer_changes_nothing(partner_world, patch):
    w = partner_world
    Currency.objects.get_or_create(code="USD", defaults={"name": "USD"})
    product = w["cards"]["published"]
    rfq, line = _rfq_on_product(w, product)
    before = SupplierOffer.objects.get(product=product, supplier=w["a"]).base_price
    body = {"answer_note": "Есть", "currency": "USD", "lines": [{"id": line.pk, "unit_price": "5.00"}], **patch}
    if body["lines"] == "dup":
        body["lines"] = [{"id": line.pk, "unit_price": "5.00"}, {"id": line.pk, "unit_price": "6.00"}]
    elif body["lines"][0]["id"] == "line":
        body["lines"] = [{"id": line.pk, "unit_price": "0"}]
    if body.get("currency") is None:
        del body["currency"]

    response = post(w["client_a"], f"price-requests/{rfq.pk}/respond", body)

    assert response.status_code == 422, response.json()
    rfq.refresh_from_db()
    assert rfq.answered_at is None
    assert SupplierOffer.objects.get(product=product, supplier=w["a"]).base_price == before


def test_price_of_a_foreign_request_line_is_refused(partner_world):
    w = partner_world
    Currency.objects.get_or_create(code="USD", defaults={"name": "USD"})
    rfq = make_rfq(w["a"])
    foreign = make_rfq(w["b"])
    line = PriceRequestLine.objects.create(request=foreign, name="Чужая", quantity=1, unit="шт")
    body = {"answer_note": "Есть", "currency": "USD", "lines": [{"id": line.pk, "unit_price": "5.00"}]}
    assert post(w["client_a"], f"price-requests/{rfq.pk}/respond", body).status_code == 422
    line.refresh_from_db()
    assert line.answer_price is None


# ── Уведомления снабжения ─────────────────────────────────────────────────────────────────────────────


def test_confirmation_notifies_the_buyer(partner_world):
    w = partner_world
    order = make_order(w["a"], expected=today() + timedelta(days=10), created_by=w["staff"])
    post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(10)})
    note = Notification.objects.get(user=w["staff"], event_code="supplier_order.partner_confirmed")
    assert order.number in note.title
    assert note.event_params["number"] == order.number and note.event_params["supplier"] == w["a"].name


def test_shipment_notifies_the_responsible_employee(partner_world):
    w = partner_world
    CompanyRelationship.objects.filter(company=w["a"], role=RelationshipRole.PARTNER).update(responsible=w["staff"])
    order = make_order(w["a"], OrderStatus.CONFIRMED)
    post(w["client_a"], f"orders/{order.pk}/ship", {"supplier_doc": "ТТН-7"})
    assert Notification.objects.filter(user=w["staff"], event_code="supplier_order.partner_shipped").count() == 1


def test_answer_notifies_the_requester(partner_world):
    w = partner_world
    rfq = make_rfq(w["a"], requested_by=w["staff"])
    post(w["client_a"], f"price-requests/{rfq.pk}/respond", {"answer_note": "Ответ"})
    assert Notification.objects.filter(user=w["staff"], event_code="rfq.partner_answered").count() == 1


def test_buyer_who_is_also_responsible_gets_one_notice(partner_world):
    w = partner_world
    CompanyRelationship.objects.filter(company=w["a"], role=RelationshipRole.PARTNER).update(responsible=w["staff"])
    order = make_order(w["a"], expected=today() + timedelta(days=5), created_by=w["staff"])
    post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(5)})
    assert Notification.objects.filter(user=w["staff"], event_code="supplier_order.partner_confirmed").count() == 1


def test_a_refused_action_notifies_nobody(partner_world):
    w = partner_world
    order = make_order(w["a"], OrderStatus.CONFIRMED, created_by=w["staff"])
    post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(5)})
    assert not Notification.objects.filter(user=w["staff"]).exists()


# ── Внутренние данные ─────────────────────────────────────────────────────────────────────────────────


def test_internal_notes_do_not_reach_the_partner(partner_world):
    w = partner_world
    order = make_order(w["a"], OrderStatus.CANCELLED)
    order.cancel_reason = SECRET_NOTE
    order.save(update_fields=["cancel_reason"])
    SupplierOrderLog.objects.create(order=order, kind=OrderLogKind.CANCELLED, detail=SECRET_NOTE)
    SupplierOrderLog.objects.create(order=order, kind=OrderLogKind.EDITED, detail=SECRET_NOTE)
    SupplierOrderLog.objects.create(order=order, kind=OrderLogKind.CREATED, detail=SECRET_NOTE)
    receipt = GoodsReceipt.objects.create(order=order, supplier_doc="ТТН-5", note=SECRET_NOTE)
    GoodsReceiptLine.objects.create(receipt=receipt, order_line=order.lines.first(), quantity=1)

    response = w["client_a"].get(f"{PREFIX}/orders/{order.pk}")

    assert response.status_code == 200
    assert SECRET_NOTE not in response.content.decode()
    body = response.json()
    assert "cancel_reason" not in body
    assert "note" not in body["receipts"][0]
    assert {log["kind"] for log in body["logs"]} == {"cancelled"}
    assert all("detail" not in log for log in body["logs"])


def test_order_without_currency_is_not_shown_in_rubles(partner_world):
    w = partner_world
    order = make_order(w["a"], currency=None)
    listed = w["client_a"].get(f"{PREFIX}/orders").json()["items"][0]
    assert listed["currency"] is None
    assert w["client_a"].get(f"{PREFIX}/orders/{order.pk}").json()["currency"] is None


def test_order_currency_is_passed_through(partner_world):
    w = partner_world
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD"})[0]
    make_order(w["a"], currency=usd)
    assert w["client_a"].get(f"{PREFIX}/orders").json()["items"][0]["currency"] == "USD"


# ── Запросы к базе и коды ошибок ───────────────────────────────────────────────────────────────────────


def _add_receipt(order, doc):
    receipt = GoodsReceipt.objects.create(order=order, supplier_doc=doc)
    GoodsReceiptLine.objects.create(receipt=receipt, order_line=order.lines.first(), quantity=1)


def test_order_detail_has_no_n_plus_one(partner_world):
    w = partner_world
    order = make_order(w["a"], OrderStatus.CONFIRMED)
    _add_receipt(order, "Р-1")
    with CaptureQueriesContext(connection) as one:
        partner_orders.get_partner_order(w["a"], order.pk)
    for number in range(2, 6):
        _add_receipt(order, f"Р-{number}")
    with CaptureQueriesContext(connection) as many:
        partner_orders.get_partner_order(w["a"], order.pk)
    assert len(many) == len(one), [q["sql"] for q in many]


def test_price_request_list_has_no_n_plus_one(partner_world):
    w = partner_world
    make_rfq(w["a"])
    with CaptureQueriesContext(connection) as one:
        partner_orders.list_partner_price_requests(w["a"])
    for _ in range(4):
        make_rfq(w["a"])
    with CaptureQueriesContext(connection) as many:
        partner_orders.list_partner_price_requests(w["a"])
    assert len(many) == len(one), [q["sql"] for q in many]


def test_file_content_mismatch_is_a_portal_code():
    assert "FILE_CONTENT_MISMATCH" in ERROR_CODES


# ── Права: can_act и чужая компания ───────────────────────────────────────────────────────────────────


def _viewer_of(company):
    contact = Contact.objects.create(
        company=company, name="Наблюдатель", email="viewer@plant-north.example", can_act=False, language="ru"
    )
    return client_for(contact)


@pytest.mark.parametrize(
    "path, body, status",
    [
        ("orders/{order}/confirm", {"expected_date": 5}, OrderStatus.SENT),
        ("orders/{order}/ship", {"supplier_doc": "ТТН-1"}, OrderStatus.CONFIRMED),
        ("orders/{order}/date-change", {"requested_date": 5}, OrderStatus.CONFIRMED),
        ("price-requests/{rfq}/respond", {"answer_note": "Ответ"}, OrderStatus.SENT),
    ],
)
def test_every_mutation_needs_can_act(partner_world, path, body, status):
    w = partner_world
    order = make_order(w["a"], status)
    rfq = make_rfq(w["a"])
    payload = {key: in_days(value) if isinstance(value, int) else value for key, value in body.items()}

    response = post(_viewer_of(w["a"]), path.format(order=order.pk, rfq=rfq.pk), payload)

    assert response.status_code == 403
    assert response.json() == {"detail": "FORBIDDEN"}
    order.refresh_from_db()
    rfq.refresh_from_db()
    assert order.status == status and rfq.answered_at is None


@pytest.mark.parametrize(
    "path, body, status",
    [
        ("orders/{order}/confirm", {"expected_date": 5}, OrderStatus.SENT),
        ("orders/{order}/ship", {"supplier_doc": "ТТН-1"}, OrderStatus.CONFIRMED),
        ("orders/{order}/date-change", {"requested_date": 5}, OrderStatus.CONFIRMED),
        ("price-requests/{rfq}/respond", {"answer_note": "Ответ"}, OrderStatus.SENT),
    ],
)
def test_foreign_objects_are_not_found(partner_world, path, body, status):
    w = partner_world
    order = make_order(w["b"], status)
    rfq = make_rfq(w["b"])
    payload = {key: in_days(value) if isinstance(value, int) else value for key, value in body.items()}
    assert post(w["client_a"], path.format(order=order.pk, rfq=rfq.pk), payload).status_code == 404


def test_partner_price_untouched_by_order_confirmation(partner_world):
    """Подтверждение заказа цену не меняет — цену обновляет только ответ на запрос цен."""
    w = partner_world
    offer = make_offer(w["cards"]["review"], w["a"], "42.00")
    order = make_order(w["a"], expected=today() + timedelta(days=5))
    post(w["client_a"], f"orders/{order.pk}/confirm", {"expected_date": in_days(5)})
    offer.refresh_from_db()
    assert offer.base_price == Decimal("42.00")
