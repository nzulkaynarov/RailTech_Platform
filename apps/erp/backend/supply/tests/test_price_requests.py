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
    assert message.to == ["sales@vendor.example"]
    # СЦ-10: партнёр видит, что запрашиваем, а не номер нашего проекта
    assert message.subject == "Запрос цены и срока поставки — Перевод стрелочный Р65 1/11 и ещё 1 позиция"
    assert deal.number not in message.subject and deal.number not in message.body
    assert deal.number not in message.alternatives[0][0]
    assert PriceRequest.objects.get(pk=body["id"]).subject == message.subject, "та же тема — в кабинете партнёра"
    assert message.reply_to == ["supply@demo.test"]
    assert "Нужны сертификаты" in message.body and "Болт путевой М22" in message.body and "100" in message.body
    assert "1000" not in message.body, "наши цены поставщику не уходят"
    # W18A-P1: письмо передано почтовому сервису CRM — «В очереди» до итога доставки
    assert EmailLog.objects.get(template="price_request").status == "QUEUED"
    assert ActivityLog.objects.filter(deal=deal, event_code="rfq.price_requested").count() == 1
    listing = api(world["reader"]).get(URL, {"deal_id": deal.pk}).json()["results"]
    assert [row["id"] for row in listing] == [body["id"]], "журнал читает любой сотрудник"


def test_request_mail_shows_quantity_with_separators(world):
    """СЦ-7: количество в письме поставщику — «20 000», не «20000.000»."""
    from notifications.tests.human_text import assert_human_text

    deal, _q, items = make_deal(world, [(world["rail"], 20000)])
    assert _ask(world, deal, items).status_code == 201
    (message,) = mail.outbox
    for part in (message.body, message.alternatives[0][0]):
        assert_human_text(part)
        assert "20\u00a0000" in part


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


@pytest.mark.parametrize(
    ("rest", "tail"),
    [
        (0, ""),
        (1, " и ещё 1 позиция"),
        (2, " и ещё 2 позиции"),
        (5, " и ещё 5 позиций"),
        (11, " и ещё 11 позиций"),
        (21, " и ещё 21 позиция"),
    ],
)
def test_items_summary_counts_in_words(rest, tail):
    from supply.services.price_requests import _summary

    assert _summary("Рельс Р65", rest) == "Рельс Р65" + tail


# ── СЦ-10: «Запросить цену» из черновика заказа ──────────────────────────────────────────────────────────────────────

STOCK = "/api/v1/stock/"


def _draft(world, lines, supplier="vendor"):
    body = {"supplier_id": world[supplier].pk, "lines": lines}
    created = api(world["supply"]).post(f"{STOCK}orders/", body, format="json")
    assert created.status_code == 201, created.json()
    return created.json()


def test_request_from_an_order_asks_the_unpriced_lines(world):
    from decimal import Decimal

    from supply.models import SupplierOrder

    draft = _draft(
        world,
        [
            {"product_id": world["rail"].pk, "quantity": 2},
            {"product_id": world["bolt"].pk, "quantity": 5, "unit_price": "10.00"},
        ],
    )
    order = SupplierOrder.objects.get(pk=draft["id"])

    response = api(world["supply"]).post(f"{STOCK}orders/{order.pk}/price-request/", {}, format="json")

    assert response.status_code == 201, response.json()
    created = PriceRequest.objects.get(pk=response.json()["id"])
    assert created.supplier_order_id == order.pk
    assert response.json()["supplier_order_number"] == order.number
    [line] = created.lines.all()
    unpriced = order.lines.get(unit_price__isnull=True)
    assert (line.order_line_id, line.product_id) == (unpriced.pk, world["rail"].pk)
    assert created.subject.startswith("Запрос цены и срока поставки — ") and order.number not in created.subject
    order.refresh_from_db()
    assert order.status == "draft"
    detail = api(world["supply"]).get(f"{STOCK}orders/{order.pk}/").json()
    assert detail["price_request"]["status"] == "sent"
    assert detail["actions"]["request_price"] is True
    assert order.lines.get(unit_price__isnull=False).unit_price == Decimal("10.00")


def test_request_from_an_order_refusals(world):
    from supply.models import SupplierOrder

    draft = _draft(world, [{"product_id": world["rail"].pk, "quantity": 2}])
    other = _draft(world, [{"product_id": world["bolt"].pk, "quantity": 1}])
    url = f"{STOCK}orders/{draft['id']}/price-request/"
    foreign_line = SupplierOrder.objects.get(pk=other["id"]).lines.get().pk

    wrong = api(world["supply"]).post(url, {"line_ids": [foreign_line]}, format="json")
    assert wrong.status_code == 404 and wrong.json()["detail"] == "LINE_NOT_FOUND"
    assert api(world["reader"]).post(url, {}, format="json").status_code == 403

    silent = _draft(world, [{"product_id": world["rail"].pk, "quantity": 1}], supplier="silent")
    no_mail = api(world["supply"]).post(f"{STOCK}orders/{silent['id']}/price-request/", {}, format="json")
    assert no_mail.status_code == 409 and no_mail.json()["detail"] == "SUPPLIER_EMAIL_REQUIRED"

    SupplierOrder.objects.filter(pk=draft["id"]).update(status="sent")
    sent = api(world["supply"]).post(url, {}, format="json")
    assert sent.status_code == 409 and sent.json()["detail"] == "ORDER_NOT_DRAFT"

    priced = _draft(world, [{"product_id": world["rail"].pk, "quantity": 1, "unit_price": "5.00"}])
    nothing = api(world["supply"]).post(f"{STOCK}orders/{priced['id']}/price-request/", {}, format="json")
    assert nothing.status_code == 409 and nothing.json()["detail"] == "NOTHING_TO_PRICE"


# ── В-2: слова клиента партнёру не уходят без подтверждения сотрудником ─────────────────────────────────────────────

CLIENT_WORDS = "Стрелка для ст. Чиланзар, ООО МетроСтрой, черт. МС-77"


def _client_words(items):
    QuoteItem.objects.filter(pk=items[0].pk).update(imported_raw_name=CLIENT_WORDS)


def _everything_partner_sees(request_id: int) -> str:
    """Тема, строки, письмо (текст и HTML) и всё, что видит партнёр в кабинете и по ссылке: проекция партнёра."""
    from portal.services import partner_orders

    saved = PriceRequest.objects.get(pk=request_id)
    parts = [saved.subject, saved.note] + [f"{line.name} {line.article}" for line in saved.lines.all()]
    for message in mail.outbox:
        parts += [message.subject, message.body] + [html for html, _mime in message.alternatives]
    projection = partner_orders.get_partner_price_request(saved.supplier, saved.pk)
    parts.append(str(projection))
    return "\n".join(str(p) for p in parts)


def test_client_words_never_reach_the_partner_unconfirmed(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2), (world["bolt"], 100)])
    _client_words(items)
    response = _ask(world, deal, items)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert [line["name"] for line in body["lines"]] == ["Перевод стрелочный Р65 1/11", "Болт путевой М22"]
    assert body["lines"][0]["article"] == world["rail"].sku
    seen = _everything_partner_sees(body["id"])
    for secret in ("Чиланзар", "МетроСтрой", "МС-77", CLIENT_WORDS):
        assert secret not in seen
    assert "Перевод стрелочный Р65 1/11" in seen


def test_a_line_without_a_card_is_not_sent_until_the_staff_names_it(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2), (world["bolt"], 100)])
    _client_words(items)
    QuoteItem.objects.filter(pk=items[0].pk).update(product=None)
    refused = _ask(world, deal, items)
    assert refused.status_code == 409 and refused.json()["detail"] == "PARTNER_NAME_REQUIRED"
    assert not PriceRequest.objects.exists() and not mail.outbox
    confirmed = _ask(world, deal, items, partner_names=[{"line_id": items[0].pk, "name": "Стрелочный перевод Р65"}])
    assert confirmed.status_code == 201, confirmed.json()
    seen = _everything_partner_sees(confirmed.json()["id"])
    assert "Стрелочный перевод Р65" in seen
    for secret in ("Чиланзар", "МетроСтрой", "МС-77"):
        assert secret not in seen


def test_the_staff_can_rename_a_card_line_and_the_subject_follows(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2)])
    response = _ask(
        world, deal, items, partner_names=[{"line_id": items[0].pk, "name": "Крестовина Р65", "article": "К-1"}]
    )
    assert response.status_code == 201
    assert response.json()["subject"].endswith("Крестовина Р65") and mail.outbox[0].subject.endswith("Крестовина Р65")
    assert response.json()["lines"][0]["article"] == "К-1"


def test_preview_shows_what_the_partner_will_see_including_the_note(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2), (world["bolt"], 100)])
    _client_words(items)
    QuoteItem.objects.filter(pk=items[1].pk).update(product=None, imported_raw_name="Наши болты для Метростроя")
    body = {"deal_id": deal.pk, "supplier_id": world["vendor"].pk, "line_ids": [i.pk for i in items], "note": "Срочно"}
    first = api(world["supply"]).post(f"{URL}preview/", body, format="json")
    assert first.status_code == 200, first.json()
    data = first.json()
    assert data["ready"] is False and data["note"] == "Срочно"
    assert [(row["source"], row["name"]) for row in data["lines"]] == [
        ("card", "Перевод стрелочный Р65 1/11"),
        ("missing", None),
    ]
    assert data["lines"][0]["client_name"] == CLIENT_WORDS  # сотрудник видит слова клиента, чтобы поправить
    assert "Чиланзар" not in data["subject"] and not mail.outbox and not PriceRequest.objects.exists()
    body["partner_names"] = [{"line_id": items[1].pk, "name": "Болт путевой"}]
    second = api(world["supply"]).post(f"{URL}preview/", body, format="json").json()
    assert second["ready"] is True and second["lines"][1]["source"] == "staff"


def test_preview_needs_the_supply_right(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2)])
    body = {"deal_id": deal.pk, "supplier_id": world["vendor"].pk, "line_ids": [items[0].pk]}
    assert api(world["reader"]).post(f"{URL}preview/", body, format="json").status_code == 403


def test_preview_works_before_the_company_is_marked_as_a_partner(world):
    """Роль «поставщик» ставится при отправке (ЕД-6): предпросмотр доступен и компании без неё, отправка — нет."""
    from parties.models import Company

    deal, _q, items = make_deal(world, [(world["rail"], 2)])
    stranger = Company.objects.create(name="Новая Компания", inn="5550001112")
    body = {"deal_id": deal.pk, "supplier_id": stranger.pk, "line_ids": [items[0].pk]}
    assert api(world["supply"]).post(f"{URL}preview/", body, format="json").status_code == 200
    assert api(world["supply"]).post(URL, body, format="json").status_code == 404


def _auto_card(product, deal=None):
    """Карточка, которую расчёт завёл из слов клиента: черновик со сделкой-источником и артикулом клиента."""
    from sales.models import Deal

    from catalog.models import ProductStatus

    draft, _ = ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})
    deal = deal or Deal.objects.first()
    type(product).objects.filter(pk=product.pk).update(
        status=draft, source_deal=deal, name=CLIENT_WORDS, manufacturer_part_number="МС-КОД-77"
    )


def test_an_unconfirmed_card_blocks_the_order_to_the_partner_and_the_price_request_from_it(world):
    deal, _q, _items = make_deal(world, [(world["rail"], 2)])
    _auto_card(world["rail"], deal)
    draft = _draft(world, [{"product_id": world["rail"].pk, "quantity": 2}])
    from inventory.tests.support import complete_order

    asked = api(world["supply"]).post(f"{STOCK}orders/{draft['id']}/price-request/", {}, format="json")
    assert asked.status_code == 409 and asked.json()["detail"] == "PARTNER_NAME_REQUIRED"
    assert not PriceRequest.objects.exists()
    # заказ с названием «из слов клиента» партнёру не уходит
    complete_order(draft["id"])
    sent = api(world["supply"]).post(f"{STOCK}orders/{draft['id']}/send/", {}, format="json")
    assert sent.status_code == 409 and sent.json()["detail"] == "PARTNER_NAME_REQUIRED"
    assert not mail.outbox
    # карточку подтвердили (опубликована) — заказ уходит
    from catalog.models import ProductStatus

    published, _ = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован"})
    type(world["rail"]).objects.filter(pk=world["rail"].pk).update(status=published, name="Перевод стрелочный Р65")
    ok = api(world["supply"]).post(f"{STOCK}orders/{draft['id']}/send/", {}, format="json")
    assert ok.status_code == 200, ok.json()


def test_the_order_line_article_does_not_carry_the_client_code_of_an_unconfirmed_card(world):
    from supply.models import SupplierOrderLine

    deal, _q, _items = make_deal(world, [(world["rail"], 2)])
    _auto_card(world["rail"], deal)
    draft = _draft(world, [{"product_id": world["rail"].pk, "quantity": 2}])
    line = SupplierOrderLine.objects.get(order_id=draft["id"])
    assert "МС-КОД-77" not in line.article


def test_client_codes_in_mpn_and_drawing_never_reach_the_partner_article(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2)])
    QuoteItem.objects.filter(pk=items[0].pk).update(mpn="МС-КОД-77", gost_drawing="ЧЕРТ-МС-1234")
    response = _ask(world, deal, items)
    assert response.status_code == 201, response.json()
    assert response.json()["lines"][0]["article"] == world["rail"].sku
    seen = _everything_partner_sees(response.json()["id"])
    assert "МС-КОД-77" not in seen and "ЧЕРТ-МС-1234" not in seen


def test_an_unconfirmed_auto_card_needs_a_staff_name_in_the_price_request(world):
    deal, _q, items = make_deal(world, [(world["rail"], 2)])
    _auto_card(world["rail"], deal)
    refused = _ask(world, deal, items)
    assert refused.status_code == 409 and refused.json()["detail"] == "PARTNER_NAME_REQUIRED"
    named = _ask(world, deal, items, partner_names=[{"line_id": items[0].pk, "name": "Перевод стрелочный"}])
    assert named.status_code == 201, named.json()
    seen = _everything_partner_sees(named.json()["id"])
    assert "Чиланзар" not in seen and "МетроСтрой" not in seen and "МС-КОД-77" not in seen
