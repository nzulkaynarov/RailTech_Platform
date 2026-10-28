"""D2-2: заказы поставщикам и приёмка (`/api/v1/stock/orders*`, `supply.services.orders`).

Нумерация ЗП-ГГГГ-NNN без пропусков; статусы черновик → отправлен → подтверждён → получен, недопустимые переходы — 409;
письмо поставщику с журналом; частичная и полная приёмка растят остаток; цены поставщика — только с `quote.view_cost_margin`
или зоной товаров; объектная проверка строк; негативные тесты прямого вызова ERP без права.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone
from inventory.models import Reservation, StockBalance, StockMovement
from inventory.tests.support import api, make_deal
from supply.models import SupplierOrder, SupplierOrderLine

from notifications.models import EmailLog

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


@pytest.fixture(autouse=True)
def locmem_mail(settings):
    """Письма — только в локальный backend почты Django: ни одной настоящей отправки."""
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


def _line(product, quantity=10, **extra):
    return {"product_id": product.pk, "quantity": quantity, **extra}


def _create(world, lines=None, *, who="supply", supplier="vendor", **extra):
    body = {"supplier_id": world[supplier].pk, "lines": lines or [_line(world["rail"], 10)], **extra}
    return api(world[who]).post(f"{STOCK}orders/", body, format="json")


def _act(world, order_id, action, body=None, who="supply"):
    return api(world[who]).post(f"{STOCK}orders/{order_id}/{action}/", body or {}, format="json")


def _tomorrow():
    return (timezone.localdate() + timedelta(days=1)).isoformat()


def _confirmed(world, lines=None, **extra):
    order_id = _create(world, lines, **extra).json()["id"]
    assert _act(world, order_id, "send").status_code == 200
    assert _act(world, order_id, "confirm", {"expected_date": _tomorrow()}).status_code == 200
    return order_id


# ── создание, номер, состав ─────────────────────────────────────────────────────────────────────────────────────────


def test_orders_get_gapless_numbers_per_year(world):
    first = _create(world)
    assert first.status_code == 201, first.json()
    year = timezone.localdate().year
    assert first.json()["number"] == f"ЗП-{year}-001" and first.json()["status"] == "draft"
    assert _create(world).json()["number"] == f"ЗП-{year}-002"
    # откат создания номер возвращает: отказавший запрос не сжигает NNN
    assert _create(world, [_line(world["mounting"], 1)]).status_code == 400
    assert _create(world).json()["number"] == f"ЗП-{year}-003"
    log = first.json()["log"]
    assert [(entry["kind"], entry["by_name"]) for entry in log] == [("created", "Supply")]


def test_create_validates_supplier_lines_and_services(world):
    assert _create(world, supplier="seller").status_code == 404, "своя компания — не поставщик"
    assert _create(world, supplier="client").status_code == 404, "клиент — не поставщик"
    missing_product = api(world["supply"]).post(
        f"{STOCK}orders/", {"supplier_id": world["vendor"].pk, "lines": [{"quantity": 1}]}, format="json"
    )
    assert missing_product.status_code == 400
    assert (
        api(world["supply"])
        .post(f"{STOCK}orders/", {"supplier_id": world["vendor"].pk, "lines": []}, format="json")
        .status_code
        == 400
    )
    service = _create(world, [_line(world["mounting"], 1)])
    assert service.status_code == 400 and service.json()["detail"] == "SERVICE_NOT_STOCKED"
    assert SupplierOrder.objects.count() == 0


def test_line_with_project_link_must_belong_to_the_deal(world):
    deal, _q, (item,) = make_deal(world, [(world["rail"], 5)])
    other, _q2, _items = make_deal(world, [(world["bolt"], 1)])
    mismatch = _create(world, [_line(world["rail"], 5, deal_id=other.pk, quote_item_id=item.pk)])
    assert mismatch.status_code == 400 and mismatch.json()["detail"] == "LINE_NOT_IN_DEAL"
    ok = _create(world, [_line(world["rail"], 5, deal_id=deal.pk, quote_item_id=item.pk)])
    assert ok.status_code == 201
    assert ok.json()["projects"] == [{"id": deal.pk, "number": deal.number, "client_name": "ООО Пример Логистик"}]


def test_line_for_another_product_than_the_calc_line_is_refused(world):
    """Строка заказа «болт» с привязкой к строке расчёта «стрелочный перевод»: резерв ушёл бы чужому товару."""
    deal, _q, (item,) = make_deal(world, [(world["rail"], 5)])
    mismatch = _create(world, [_line(world["bolt"], 5, deal_id=deal.pk, quote_item_id=item.pk)])
    assert mismatch.status_code == 400 and mismatch.json()["detail"] == "LINE_PRODUCT_MISMATCH"
    assert SupplierOrder.objects.count() == 0


def test_receiving_a_line_whose_product_card_was_deleted_is_refused(world):
    order_id = _confirmed(world)
    line = api(world["supply"]).get(f"{STOCK}orders/{order_id}/").json()["lines"][0]["id"]
    SupplierOrderLine.objects.filter(pk=line).update(product=None)  # карточку удалили (SET_NULL)
    refused = _act(world, order_id, "receipts", {"lines": [{"order_line_id": line, "quantity": 1}]})
    assert refused.status_code == 409 and refused.json() == {"detail": "PRODUCT_REQUIRED"}
    assert not StockBalance.objects.exists()


def test_editing_a_line_keeps_its_project_link_unless_it_is_resent(world):
    deal, _q, (item,) = make_deal(world, [(world["rail"], 5)])
    created = _create(world, [_line(world["rail"], 5, deal_id=deal.pk, quote_item_id=item.pk)]).json()
    line = created["lines"][0]["id"]
    kept = api(world["supply"]).patch(
        f"{STOCK}orders/{created['id']}/",
        {"lines": [{"id": line, "product_id": world["rail"].pk, "quantity": 4}]},
        format="json",
    )
    assert kept.status_code == 200 and kept.json()["lines"][0]["quote_item_id"] == item.pk
    unlinked = api(world["supply"]).patch(
        f"{STOCK}orders/{created['id']}/",
        {
            "lines": [
                {"id": line, "product_id": world["rail"].pk, "quantity": 4, "deal_id": None, "quote_item_id": None}
            ]
        },
        format="json",
    )
    assert unlinked.json()["lines"][0]["quote_item_id"] is None and unlinked.json()["projects"] == []


def test_edit_in_draft_replaces_lines_and_keeps_prices_that_are_not_resent(world):
    created = _create(world, [_line(world["rail"], 2, unit_price="90000.00"), _line(world["bolt"], 10)])
    body = created.json()
    order_id, first, second = body["id"], body["lines"][0], body["lines"][1]
    patched = api(world["engineer"]).patch(
        f"{STOCK}orders/{order_id}/",
        {"lines": [{"id": first["id"], "product_id": world["rail"].pk, "quantity": 3}], "note": "Срочно"},
        format="json",
    )
    assert patched.status_code == 200, patched.json()
    lines = SupplierOrderLine.objects.filter(order_id=order_id)
    assert [(row.pk, row.quantity, row.unit_price) for row in lines] == [
        (first["id"], 3, Decimal("90000.00"))
    ], "цена не пересылалась — не стёрта; строка без id в теле удалена"
    assert second["id"] not in {row.pk for row in lines}
    foreign_line = _create(world).json()["lines"][0]["id"]
    foreign = api(world["supply"]).patch(
        f"{STOCK}orders/{order_id}/",
        {"lines": [{"id": foreign_line, "product_id": world["rail"].pk, "quantity": 1}]},
        format="json",
    )
    assert foreign.status_code == 404, "строка чужого заказа не правится"


def test_supplier_prices_follow_the_price_rule(world):
    refused = _create(world, [_line(world["rail"], 1, unit_price="100.00")], who="engineer")
    assert refused.status_code == 403 and refused.json() == {"detail": "PRICES_FORBIDDEN"}
    created = _create(world, [_line(world["rail"], 4, unit_price="250.50")])
    assert created.json()["total"] == "1002.00"
    order_id = created.json()["id"]
    for who in ("engineer", "reader"):
        seen = api(world[who]).get(f"{STOCK}orders/{order_id}/").json()
        assert (
            seen["total"] is None and seen["lines"][0]["unit_price"] is None and seen["lines"][0]["line_total"] is None
        ), who
        listed = api(world[who]).get(f"{STOCK}orders/").json()["results"][0]
        assert listed["total"] is None, who
    engineer_edit = api(world["engineer"]).patch(
        f"{STOCK}orders/{order_id}/",
        {
            "lines": [
                {
                    "id": created.json()["lines"][0]["id"],
                    "product_id": world["rail"].pk,
                    "quantity": 4,
                    "unit_price": "1.00",
                }
            ]
        },
        format="json",
    )
    assert engineer_edit.status_code == 403
    assert SupplierOrderLine.objects.get(order_id=order_id).unit_price == Decimal("250.50")


# ── статусы и письмо ────────────────────────────────────────────────────────────────────────────────────────────────


def test_send_mails_the_supplier_and_writes_the_journal(world):
    order = _create(world, [_line(world["rail"], 2, unit_price="90000.00")], expected_date=_tomorrow()).json()
    sent = _act(world, order["id"], "send")
    assert sent.status_code == 200, sent.json()
    body = sent.json()
    assert body["status"] == "sent" and body["sent_to"] == "sales@vendor.example"
    assert [entry["kind"] for entry in body["log"]] == ["created", "sent"]
    (message,) = mail.outbox
    assert message.to == ["sales@vendor.example"] and order["number"] in message.subject
    assert message.reply_to == ["supply@demo.test"], "ответ поставщика придёт снабженцу"
    assert "Перевод стрелочный Р65 1/11" in message.body and "90000.00" in message.body
    log = EmailLog.objects.get(template="supplier_order")
    assert log.status == "SENT" and log.to_emails == ["sales@vendor.example"]


def test_send_needs_an_address_and_a_failed_mail_leaves_the_order_a_draft(world, monkeypatch):
    silent = _create(world, supplier="silent").json()
    refused = _act(world, silent["id"], "send")
    assert refused.status_code == 409 and refused.json() == {"detail": "SUPPLIER_EMAIL_REQUIRED"}
    override = _act(world, silent["id"], "send", {"to_email": "orders@silent.example"})
    assert override.status_code == 200 and override.json()["sent_to"] == "orders@silent.example"

    from notifications.emails import EmailDeliveryError

    def broken(*args, **kwargs):
        raise EmailDeliveryError("smtp down (test)")

    monkeypatch.setattr("notifications.emails.send_templated_email", broken)
    draft = _create(world).json()
    failed = _act(world, draft["id"], "send")
    assert failed.status_code == 409 and failed.json() == {"detail": "EMAIL_FAILED"}
    assert SupplierOrder.objects.get(pk=draft["id"]).status == "draft", "статус не сменился"


def test_only_allowed_transitions_and_the_expected_date_gate(world):
    order_id = _create(world).json()["id"]
    for action in ("confirm",):
        assert _act(world, order_id, action).status_code == 409, "черновик нельзя подтвердить"
    assert _act(world, order_id, "receipts", {"lines": [{"order_line_id": 1, "quantity": 1}]}).status_code == 409
    assert _act(world, order_id, "send").status_code == 200
    again = _act(world, order_id, "send")
    assert again.status_code == 409 and again.json()["detail"] == "TRANSITION_NOT_ALLOWED"
    no_date = _act(world, order_id, "confirm")
    assert no_date.status_code == 409 and no_date.json() == {"detail": "EXPECTED_DATE_REQUIRED"}
    confirmed = _act(world, order_id, "confirm", {"expected_date": _tomorrow()})
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    assert _act(world, order_id, "confirm", {"expected_date": _tomorrow()}).status_code == 409
    cancelled = _act(world, order_id, "cancel", {"reason": "Поставщик не успевает"})
    assert cancelled.status_code == 200 and cancelled.json()["cancel_reason"] == "Поставщик не успевает"
    for action in ("send", "confirm", "cancel"):
        assert _act(world, order_id, action).status_code == 409, action
    assert api(world["supply"]).patch(f"{STOCK}orders/{order_id}/", {"note": "x"}, format="json").status_code == 409


def test_edit_of_a_sent_order_is_limited_to_the_date_and_note(world):
    order_id = _create(world).json()["id"]
    _act(world, order_id, "send")
    lines_refused = api(world["supply"]).patch(
        f"{STOCK}orders/{order_id}/", {"lines": [_line(world["rail"], 1)]}, format="json"
    )
    assert lines_refused.status_code == 409 and lines_refused.json()["detail"] == "ORDER_NOT_DRAFT"
    ok = api(world["supply"]).patch(
        f"{STOCK}orders/{order_id}/", {"expected_date": _tomorrow(), "note": "Перенесли"}, format="json"
    )
    assert ok.status_code == 200 and ok.json()["expected_date"] == _tomorrow()


# ── приёмка ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_partial_then_full_receipt_grows_stock_and_closes_the_order(world):
    order_id = _confirmed(world, [_line(world["rail"], 10), _line(world["bolt"], 4)])
    lines = api(world["supply"]).get(f"{STOCK}orders/{order_id}/").json()["lines"]
    rail_line, bolt_line = lines[0]["id"], lines[1]["id"]

    partial = _act(
        world,
        order_id,
        "receipts",
        {"lines": [{"order_line_id": rail_line, "quantity": 6, "cell": "B-02"}], "supplier_doc": "НП-77"},
    )
    assert partial.status_code == 200, partial.json()
    body = partial.json()
    assert body["status"] == "confirmed" and body["receipt_state"] == "partial"
    assert body["receipts"][0]["supplier_doc"] == "НП-77" and body["receipts"][0]["lines"][0]["cell"] == "B-02"
    assert StockBalance.objects.get(product=world["rail"]).on_hand == 6
    assert body["actions"]["cancel"] is False, "после приёмки отменить нельзя"
    assert _act(world, order_id, "cancel").json() == {"detail": "ORDER_HAS_RECEIPTS"}

    over = _act(world, order_id, "receipts", {"lines": [{"order_line_id": rail_line, "quantity": 5}]})
    assert over.status_code == 400 and over.json() == {"detail": "QUANTITY_OUT_OF_RANGE", "max": 4}
    assert StockBalance.objects.get(product=world["rail"]).on_hand == 6, "отказ ничего не принял"

    full = _act(
        world,
        order_id,
        "receipts",
        {
            "lines": [
                {"order_line_id": rail_line, "quantity": 4, "cell": "B-02"},
                {"order_line_id": bolt_line, "quantity": 4},
            ]
        },
    )
    assert full.status_code == 200 and full.json()["status"] == "received" and full.json()["receipt_state"] == "full"
    assert StockBalance.objects.get(product=world["rail"], cell="B-02").on_hand == 10
    assert StockBalance.objects.get(product=world["bolt"]).on_hand == 4
    assert StockMovement.objects.filter(kind="receipt").count() == 3
    kinds = [entry["kind"] for entry in full.json()["log"]]
    assert kinds == ["created", "sent", "confirmed", "receipt", "receipt", "received"]
    assert (
        _act(world, order_id, "receipts", {"lines": [{"order_line_id": rail_line, "quantity": 1}]}).status_code == 409
    )


def test_receipt_object_check_and_duplicates(world):
    order_a = _confirmed(world)
    order_b = _confirmed(world)
    line_b = api(world["supply"]).get(f"{STOCK}orders/{order_b}/").json()["lines"][0]["id"]
    foreign = _act(world, order_a, "receipts", {"lines": [{"order_line_id": line_b, "quantity": 1}]})
    assert foreign.status_code == 404 and foreign.json() == {"detail": "LINE_NOT_FOUND"}, "строка чужого заказа"
    line_a = api(world["supply"]).get(f"{STOCK}orders/{order_a}/").json()["lines"][0]["id"]
    dup = _act(world, order_a, "receipts", {"lines": [{"order_line_id": line_a, "quantity": 1}] * 2})
    assert dup.status_code == 400
    assert not StockBalance.objects.exists()


def test_received_goods_are_reserved_for_the_project_line(world):
    deal, _q, (item,) = make_deal(world, [(world["rail"], 3)])
    order_id = _confirmed(world, [_line(world["rail"], 5, deal_id=deal.pk, quote_item_id=item.pk)])
    line = api(world["supply"]).get(f"{STOCK}orders/{order_id}/").json()["lines"][0]["id"]
    _act(world, order_id, "receipts", {"lines": [{"order_line_id": line, "quantity": 2}]})
    assert Reservation.objects.get(quote_item=item).quantity == 2
    _act(world, order_id, "receipts", {"lines": [{"order_line_id": line, "quantity": 3}]})
    reservation = Reservation.objects.get(quote_item=item)
    assert reservation.quantity == 3, "резерв не больше количества строки КП; лишнее — свободно на складе"
    row = api(world["supply"]).get(f"{STOCK}balances/", {"q": "стрелочный"}).json()["results"][0]
    assert (row["on_hand"], row["reserved"], row["free"]) == (5, 3, 2)


def test_order_for_a_project_shortage(world):
    from inventory.tests.test_stock import _adjust, _reserve

    deal, _q, (rail, bolt) = make_deal(world, [(world["rail"], 5), (world["bolt"], 8)])
    _adjust(world, world["rail"], 2)
    assert _reserve(world, deal, rail, 2).status_code == 201
    response = api(world["supply"]).post(
        f"{STOCK}orders/from-deal/", {"deal_id": deal.pk, "supplier_id": world["vendor"].pk}, format="json"
    )
    assert response.status_code == 201, response.json()
    assert [(row["name"], row["quantity"]) for row in response.json()["lines"]] == [
        ("Перевод стрелочный Р65 1/11", 3),
        ("Болт путевой М22", 8),
    ], "дефицит = количество строки − резерв"
    again = api(world["supply"]).post(
        f"{STOCK}orders/from-deal/", {"deal_id": deal.pk, "supplier_id": world["vendor"].pk}, format="json"
    )
    assert again.status_code == 409 and again.json() == {"detail": "NO_SHORTAGE"}, "уже заказано в живом ЗП"


# ── права ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_role_matrix_on_orders(world):
    order_id = _create(world).json()["id"]
    reader, shipper, outsider = api(world["reader"]), api(world["shipper"]), api(world["outsider"])
    for client in (reader, shipper, outsider):
        assert (
            client.post(
                f"{STOCK}orders/", {"supplier_id": world["vendor"].pk, "lines": [_line(world["rail"])]}, format="json"
            ).status_code
            == 403
        )
        assert client.patch(f"{STOCK}orders/{order_id}/", {"note": "x"}, format="json").status_code == 403
        for action in ("send", "confirm", "cancel", "receipts"):
            assert client.post(f"{STOCK}orders/{order_id}/{action}/", {}, format="json").status_code == 403, action
        assert (
            client.post(f"{STOCK}orders/from-deal/", {"deal_id": 1, "supplier_id": 1}, format="json").status_code == 403
        )
    assert reader.get(f"{STOCK}orders/{order_id}/").status_code == 200
    assert reader.get(f"{STOCK}orders/").json()["rights"] == {"manage": False, "ship": False, "prices": False}
    assert outsider.get(f"{STOCK}orders/{order_id}/").status_code == 403
    assert SupplierOrder.objects.get(pk=order_id).status == "draft" and SupplierOrder.objects.count() == 1


def test_listing_filters(world):
    draft = _create(world).json()
    sent = _create(world, supplier="silent").json()
    _act(world, sent["id"], "send", {"to_email": "orders@silent.example"})

    def names(params):
        return [row["number"] for row in api(world["reader"]).get(f"{STOCK}orders/", params).json()["results"]]

    assert names({}) == [sent["number"], draft["number"]]
    assert names({"status": "sent"}) == [sent["number"]]
    assert names({"supplier_id": world["vendor"].pk}) == [draft["number"]]
    assert names({"number": draft["number"]}) == [draft["number"]]
    assert names({"q": "стрелочный"}) == [sent["number"], draft["number"]]
    assert names({"overdue": "1"}) == []
    missing = api(world["reader"]).get(f"{STOCK}orders/999999/")
    assert missing.status_code == 404 and missing.json() == {"detail": "ORDER_NOT_FOUND"}
