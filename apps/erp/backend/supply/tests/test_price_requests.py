"""D2-2: «Запросить цену у поставщика» из расчёта — письмо поставщику и журнал (`/api/v1/stock/price-requests/`).

Письма — только в локальный backend почты Django; поставщики и адреса вымышленные (`*.example`). Журнал: кто, когда, кому, по
каким строкам; сбой почты остаётся в журнале «не отправлен»; объектная проверка строк; негативные тесты без права.
"""

from __future__ import annotations

import pytest
from django.core import mail
from inventory.tests.support import api, make_deal
from supply.models import PriceRequest

from crm.models import ActivityLog, CalcLine, QuoteItem
from notifications.models import EmailLog

pytestmark = pytest.mark.django_db

URL = "/api/v1/stock/price-requests/"


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


def _ask(world, deal, items, *, who="supply", supplier="vendor", **extra):
    body = {"deal_id": deal.pk, "supplier_id": world[supplier].pk, "line_ids": [i.pk for i in items], **extra}
    return api(world[who]).post(URL, body, format="json")


def test_request_goes_to_the_supplier_and_is_journaled(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2), (world["bolt"], 100)])
    response = _ask(world, deal, items, note="Нужны сертификаты")
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "sent" and body["to_email"] == "sales@vendor.example"
    assert body["requested_by_name"] == "Supply" and body["deal_number"] == deal.number
    assert [(line["name"], line["quantity"]) for line in body["lines"]] == [
        ("Перевод стрелочный Р65 1/11", 2),
        ("Болт путевой М22", 100),
    ]
    (message,) = mail.outbox
    assert message.to == ["sales@vendor.example"] and deal.number in message.subject
    assert message.reply_to == ["supply@demo.test"]
    assert "Нужны сертификаты" in message.body and "Болт путевой М22" in message.body and "100" in message.body
    assert "1000" not in message.body, "наши цены поставщику не уходят"
    assert EmailLog.objects.get(template="price_request").status == "SENT"
    assert ActivityLog.objects.filter(deal=deal, event_code="rfq.price_requested").count() == 1
    listing = api(world["reader"]).get(URL, {"deal_id": deal.pk}).json()["results"]
    assert [row["id"] for row in listing] == [body["id"]], "журнал читает любой сотрудник"


def test_a_failed_mail_stays_in_the_journal(world, monkeypatch):
    deal, _q, items = make_deal(world, [(world["rail"], 2)])
    from notifications.models import EmailLog as Log

    def failed(*args, **kwargs):
        return Log(status=Log.STATUS_FAILED, error="OSError: smtp down (test)")

    monkeypatch.setattr("notifications.emails.send_templated_email", failed)
    response = _ask(world, deal, items)
    assert response.status_code == 201 and response.json()["status"] == "failed"
    assert response.json()["error"] == "OSError: smtp down (test)"
    assert PriceRequest.objects.get().status == "failed"
    assert api(world["supply"]).post(f"{URL}{response.json()['id']}/answer/", {}, format="json").json() == {
        "detail": "REQUEST_NOT_SENT"
    }


def test_supplier_must_be_reachable_and_lines_must_be_goods_of_this_deal(world):
    deal, quote, items = make_deal(world, [(world["rail"], 2)])
    no_mail = _ask(world, deal, items, supplier="silent")
    assert no_mail.status_code == 409 and no_mail.json() == {"detail": "SUPPLIER_EMAIL_REQUIRED"}
    override = _ask(world, deal, items, supplier="silent", to_email="sales@silent.example")
    assert override.status_code == 201 and override.json()["to_email"] == "sales@silent.example"

    service = QuoteItem(quote=quote, position=5, product=world["mounting"], imported_raw_name="Монтаж", quantity=1)
    service.save(skip_recalculate=True)
    CalcLine.objects.create(item=service, kind="service")
    assert _ask(world, deal, [service]).json() == {"detail": "LINE_NOT_GOODS"}

    other, _q2, other_items = make_deal(world, [(world["bolt"], 1)])
    foreign = _ask(world, deal, other_items)
    assert foreign.status_code == 404 and foreign.json() == {"detail": "LINE_NOT_FOUND"}, "строка чужой заявки"
    assert _ask(world, deal, [], supplier="vendor").status_code == 400
    assert _ask(world, deal, items, supplier="seller").status_code == 404, "своя компания — не поставщик"
    assert _ask(world, deal, items, supplier="client").status_code == 404
    unknown_deal = api(world["supply"]).post(
        URL, {"deal_id": 999999, "supplier_id": world["vendor"].pk, "line_ids": [1]}, format="json"
    )
    assert unknown_deal.status_code == 404
    assert PriceRequest.objects.count() == 1


def test_role_matrix_and_the_answer(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2)])
    for who in ("reader", "shipper", "outsider"):
        assert _ask(world, deal, items, who=who).status_code == 403, who
    assert PriceRequest.objects.count() == 0
    assert api(world["outsider"]).get(URL).status_code == 403
    created = _ask(world, deal, items, who="engineer")
    assert created.status_code == 201, "у гл. инженера есть supply.manage — запрос цены ему доступен"
    request_id = created.json()["id"]
    assert api(world["reader"]).post(f"{URL}{request_id}/answer/", {}, format="json").status_code == 403
    answered = api(world["supply"]).post(f"{URL}{request_id}/answer/", {"note": "90 млн, 45 дней"}, format="json")
    assert answered.status_code == 200
    assert answered.json()["answer_note"] == "90 млн, 45 дней" and answered.json()["answered_by_name"] == "Supply"
    again = api(world["supply"]).post(f"{URL}{request_id}/answer/", {}, format="json")
    assert again.status_code == 409 and again.json() == {"detail": "ALREADY_ANSWERED"}
    assert api(world["supply"]).post(f"{URL}999999/answer/", {}, format="json").status_code == 404
