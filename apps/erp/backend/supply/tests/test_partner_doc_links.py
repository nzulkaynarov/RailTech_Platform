"""ДК-5: запрос цены и заказ поставщику уходят партнёру по личной ссылке (ADR-0030) — как документы клиента.

Проверяются факты, от которых зависят безопасность и сценарий: ссылка привязана к получателю, документу и виду; партнёр не
видит ни клиента заявки, ни нашей цены продажи; «подтверждён» ставит только партнёр сам; права действий не шире прав
контакта; отзыв гасит ссылки ЭТОГО документа; письмо одно — PDF и кнопка на ссылку контакта.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from inventory.tests.support import api, make_deal
from parties.models import Company, CompanyRelationship, Contact
from portal.models import DocumentLink, NoticeEmailState, PortalNotice
from portal.services import doc_links, notices
from portal.services.tokens import hash_token
from portal.tests.conftest import PortalAPIClient
from portal.tests.partner_world import client_for
from rest_framework import status
from supply.models import OrderStatus, PriceRequest, PriceRequestStatus, SupplierOrder
from supply.tests.test_orders import (  # noqa: F401 — autouse: только локальная почта
    _act,
    _create,
    _tomorrow,
    locmem_mail,
)

from notifications.models import EmailLog

pytestmark = pytest.mark.django_db

BASE = "/api/portal/v1/doc-links"
STOCK = "/api/v1/stock/"
CLIENT_SECRET = "ООО Пример Логистик"  # клиент заявки: партнёр его не видит


@pytest.fixture(autouse=True)
def _env(settings):
    settings.CABINET_URL = "http://cabinet.localhost"
    cache.clear()


def _partner(world, *, can_act=True, modules=("my_products",), email="dilshod@vendor.example"):
    CompanyRelationship.objects.create(
        company=world["vendor"], role="partner", status="active", modules=list(modules), activated_at=timezone.now()
    )
    return Contact.objects.create(
        company=world["vendor"], name="Dilshod", email=email, language="ru", can_act=can_act, invited_at=timezone.now()
    )


def _post(path, data=None, client=None):
    return (client or PortalAPIClient()).post(f"{BASE}/{path}", data or {}, format="json")


def _order(world) -> dict:
    created = _create(
        world,
        expected_date=_tomorrow(),
        lines=[{"product_id": world["rail"].pk, "quantity": 3, "unit_price": "100.00"}],
    )
    assert created.status_code == 201, created.json()
    return created.json()


def _sent_order(world) -> SupplierOrder:
    order = _order(world)
    assert _act(world, order["id"], "send").status_code == 200
    return SupplierOrder.objects.get(pk=order["id"])


def _deliver_all(kind: str) -> list[PortalNotice]:
    """Письма-уведомления партнёру уходят после коммита; в тесте (без коммита) — вызываем сборщик строки сами."""
    rows = list(PortalNotice.objects.filter(kind=kind, email_state=NoticeEmailState.PENDING))
    for row in rows:
        assert notices.deliver_email(row.pk) == "sent"
    return rows


def _link_of(mail_message) -> str:
    return re.search(r"/d/([A-Za-z0-9_-]{20,})", mail_message.body).group(1)


def _request(world, *, with_deal=True) -> PriceRequest:
    deal, _quote, items = make_deal(world, [(world["rail"], 5)], approved=True)
    created = api(world["supply"]).post(
        f"{STOCK}price-requests/",
        {"deal_id": deal.pk, "supplier_id": world["vendor"].pk, "line_ids": [items[0].pk]},
        format="json",
    )
    assert created.status_code == 201, created.json()
    return PriceRequest.objects.get(pk=created.json()["id"])


def _verified(raw: str) -> PortalAPIClient:
    assert _post("code", {"token": raw}).status_code == status.HTTP_202_ACCEPTED
    code = re.search(r"(\d{6})", mail.outbox[-1].body).group(1)
    client = PortalAPIClient()
    response = _post("verify", {"token": raw, "code": code}, client)
    assert response.status_code == 200, response.content
    return client


def _mint(kind, doc, contact):
    link, raw = doc_links.mint_document_link(kind, doc, contact.email, contact.name)
    return link, raw


# ── Письмо: одно, с PDF и кнопкой на ссылку контакта ────────────────────────────────────────────────────────────────


def test_order_goes_out_as_one_letter_with_the_pdf_and_the_contact_link(world):
    contact = _partner(world)
    order = _sent_order(world)
    rows = _deliver_all("partner_order_sent")
    assert len(rows) == 1 and rows[0].contact_id == contact.pk
    letters = [m for m in mail.outbox if m.to == [contact.email]]
    assert len(letters) == 1, "одно письмо на заказ"
    message = letters[0]
    assert len(message.attachments) == 1 and message.attachments[0][0].endswith(".pdf")
    assert message.attachments[0][2] == "application/pdf" and message.attachments[0][1][:4] == b"%PDF"
    raw = _link_of(message)
    link = DocumentLink.objects.get()
    assert link.token_hash == hash_token(raw) and raw not in link.token_hash, "в базе только хеш"
    assert (link.kind, link.supplier_order_id, link.contact_id) == ("supplier_order", order.pk, contact.pk)
    assert link.recipient_email == contact.email and link.quote_id is None and link.price_request_id is None
    assert not EmailLog.objects.filter(template="supplier_order").exists(), "письма «ответьте на это» нет"


def test_price_request_goes_out_as_one_letter_with_the_pdf_and_the_contact_link(world):
    contact = _partner(world)
    Company.objects.filter(pk=world["vendor"].pk).update(email=contact.email)  # общая почта — адрес этого контакта
    req = _request(world)
    rows = _deliver_all("partner_rfq_sent")
    assert len(rows) == 1 and rows[0].contact_id == contact.pk
    letters = [m for m in mail.outbox if m.to == [contact.email]]
    assert len(letters) == 1, "одно письмо на запрос"
    assert len(letters[0].attachments) == 1 and letters[0].attachments[0][1][:4] == b"%PDF"
    link = DocumentLink.objects.get(token_hash=hash_token(_link_of(letters[0])))
    assert (link.kind, link.price_request_id, link.contact_id) == ("price_request", req.pk, contact.pk)
    assert not EmailLog.objects.filter(template="price_request").exists(), "то же письмо, что на общий адрес, не шлём"


def test_a_shared_mailbox_gets_the_old_letter_that_never_asks_to_reply(world):
    contact = _partner(world)  # общая почта поставщика (sales@…) — не контакт: письмо со ссылкой ей не адресовано
    _request(world)
    _deliver_all("partner_rfq_sent")
    shared = next(m for m in mail.outbox if m.to == ["sales@vendor.example"])
    assert "ответьте" not in shared.body.lower() and "личном кабинете партнёра" in shared.body
    assert not shared.attachments and "/d/" not in shared.body, "ссылка — только контакту, на чей адрес она выпущена"
    assert len([m for m in mail.outbox if m.to == [contact.email]]) == 1


def test_a_failed_letter_leaves_no_live_link(world, monkeypatch):
    _partner(world)
    _sent_order(world)
    from notifications import emails

    monkeypatch.setattr(
        emails,
        "send_templated_email",
        lambda *a, **k: type("L", (), {"status": EmailLog.STATUS_FAILED, "error": "x"})(),
    )
    row = PortalNotice.objects.get(kind="partner_order_sent")
    notices.deliver_email(row.pk)
    assert DocumentLink.objects.get().revoked_at is not None, "ссылка, которой нет у получателя, не остаётся живой"


# ── Гость: только партнёрская проекция ──────────────────────────────────────────────────────────────────────────────


def test_guest_view_of_a_price_request_has_no_client_and_no_sale_price(world):
    contact = _partner(world)
    req = _request(world)
    link, raw = _mint("price_request", req, contact)
    response = _post("open", {"token": raw})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "price_request" and body["actions"] == ["answer"] and body["state"] == "open"
    assert body["from_name"] == world["seller"].name or body["from_name"] == ""
    assert body["to_name"] == world["vendor"].name
    assert [line["name"] for line in body["partner_lines"]] == [world["rail"].name]
    text = response.content.decode()
    assert CLIENT_SECRET not in text and "1000" not in text and req.deal.number not in text
    for forbidden in ("margin", "cost", "sale_price", "deal"):
        assert forbidden not in body, forbidden


def test_guest_view_of_an_order_has_the_partner_prices_only(world):
    contact = _partner(world)
    order = _sent_order(world)
    _link, raw = _mint("supplier_order", order, contact)
    body = _post("open", {"token": raw}).json()
    assert body["kind"] == "supplier_order" and body["actions"] == ["confirm"] and body["state"] == "open"
    assert body["total"]["amount"].startswith("300") and body["expected_date"] == _tomorrow()
    assert body["partner_lines"][0]["unit_price"]["amount"].startswith("100")
    assert "note" not in body and "internal" not in str(body)


def test_pdf_is_built_from_the_partner_projection_only(world, monkeypatch):
    contact = _partner(world)
    req = _request(world)
    _link, raw = _mint("price_request", req, contact)
    seen = {}
    from supply.services import partner_documents

    real = partner_documents._render

    def spy(context, language):
        seen.update(context)
        return real(context, language)

    monkeypatch.setattr(partner_documents, "_render", spy)
    response = _post("pdf", {"token": raw})
    assert response.status_code == 200 and response.content[:4] == b"%PDF"
    assert "attachment" in response["Content-Disposition"]
    assert CLIENT_SECRET not in str(seen) and "deal" not in seen
    assert seen["supplier"] == world["vendor"].name


def test_a_draft_order_and_an_undelivered_request_are_not_shown(world):
    contact = _partner(world)
    draft = SupplierOrder.objects.get(pk=_order(world)["id"])
    _l, raw_order = _mint("supplier_order", draft, contact)
    assert _post("open", {"token": raw_order}).status_code == 410
    req = _request(world)
    PriceRequest.objects.filter(pk=req.pk).update(status=PriceRequestStatus.FAILED)
    req.refresh_from_db()
    _l, raw_req = _mint("price_request", req, contact)
    assert _post("open", {"token": raw_req}).status_code == 410


# ── Связка ссылки: получатель + документ + вид ──────────────────────────────────────────────────────────────────────


def test_link_kind_must_match_its_one_document(world):
    contact = _partner(world)
    order = _sent_order(world)
    req = _request(world)
    for kind, fields in (
        ("supplier_order", {"price_request": req}),  # вид называет заказ, а заполнен запрос
        ("price_request", {"supplier_order": order, "price_request": req}),  # два документа сразу
        ("price_request", {}),  # ни одного
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            DocumentLink.objects.create(
                token_hash=f"h{kind}{len(fields)}",
                kind=kind,
                recipient_email=contact.email,
                expires_at=timezone.now() + timedelta(days=5),
                **fields,
            )


def test_a_link_never_acts_on_another_document_or_company(world):
    contact = _partner(world)
    other = Company.objects.create(name="ООО Другой Поставщик", inn="7700000999")
    stranger = Contact.objects.create(
        company=other, name="Чужой", email="x@other.example", can_act=True, invited_at=timezone.now()
    )
    CompanyRelationship.objects.create(company=other, role="partner", status="active", modules=["my_products"])
    order = _sent_order(world)
    _link, raw = _mint("supplier_order", order, contact)
    foreign = client_for(stranger)
    response = foreign.post(
        f"{BASE}/act", {"token": raw, "action": "confirm", "expected_date": _tomorrow()}, format="json"
    )
    assert response.status_code == 403
    assert _post("open", {"token": raw}, foreign).json()["session"] == "other_company"
    order.refresh_from_db()
    assert order.status == OrderStatus.SENT


def test_an_action_of_another_kind_is_refused(world):
    contact = _partner(world)
    order = _sent_order(world)
    _link, raw = _mint("supplier_order", order, contact)
    client = client_for(contact)
    response = client.post(f"{BASE}/act", {"token": raw, "action": "answer", "text": "x"}, format="json")
    assert response.status_code == 422


# ── Ответ на запрос цены по ссылке ──────────────────────────────────────────────────────────────────────────────────


def test_partner_answers_the_price_request_from_the_letter(world):
    contact = _partner(world)
    req = _request(world)
    _link, raw = _mint("price_request", req, contact)
    guest = _post("open", {"token": raw}).json()
    assert guest["decide"]["allowed"] is True
    client = _verified(raw)
    line = req.lines.get()
    response = client.post(
        f"{BASE}/act",
        {
            "token": raw,
            "action": "answer",
            "text": "Цена действует месяц",
            "currency": "UZS",
            "prices": [{"id": line.pk, "unit_price": "1500.50", "lead_days": 14}],
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    req.refresh_from_db()
    line.refresh_from_db()
    assert req.answered_at is not None and req.answer_note == "Цена действует месяц" and req.answered_by_id is None
    assert line.answer_price == Decimal("1500.50") and line.answer_lead_days == 14
    body = response.json()
    assert body["state"] == "answered" and body["decide"]["allowed"] is False
    assert body["partner_lines"][0]["lead_days"] == 14 and body["partner_lines"][0]["unit_price"]["amount"].startswith(
        "1"
    )
    # второй раз — нельзя: ответ один
    again = client.post(f"{BASE}/act", {"token": raw, "action": "answer", "text": "ещё"}, format="json")
    assert again.status_code == 409


def test_a_price_row_from_another_request_is_refused(world):
    contact = _partner(world)
    mine, other = _request(world), _request(world)
    _link, raw = _mint("price_request", mine, contact)
    client = _verified(raw)
    response = client.post(
        f"{BASE}/act",
        {
            "token": raw,
            "action": "answer",
            "text": "x",
            "currency": "UZS",
            "prices": [{"id": other.lines.get().pk, "unit_price": "10.00"}],
        },
        format="json",
    )
    assert response.status_code == 422
    mine.refresh_from_db()
    assert mine.answered_at is None and not other.lines.exclude(answer_price=None).exists()


# ── Подтверждение заказа: только партнёр сам, права не шире контакта ─────────────────────────────────────────────────


def test_order_is_confirmed_only_when_the_partner_confirms_it_himself(world):
    contact = _partner(world)
    order = _sent_order(world)
    staff = _act(world, order.pk, "confirm", {"expected_date": _tomorrow()})
    assert staff.status_code == 409 and staff.json()["detail"] == "PARTNER_CONFIRMS_IN_CABINET"
    order.refresh_from_db()
    assert order.status == OrderStatus.SENT, "сотрудник за партнёра не подтверждает"

    _link, raw = _mint("supplier_order", order, contact)
    client = _verified(raw)
    response = client.post(f"{BASE}/act", {"token": raw, "action": "confirm"}, format="json")
    assert response.status_code == 200, response.content
    order.refresh_from_db()
    assert order.status == OrderStatus.CONFIRMED and order.confirmed_at is not None
    assert order.log.filter(kind="confirmed", detail__startswith="Подтверждён поставщиком").exists()
    assert response.json()["state"] == "confirmed" and response.json()["confirmed_at"]
    assert client.post(f"{BASE}/act", {"token": raw, "action": "confirm"}, format="json").status_code == 409


def test_confirmation_needs_a_date_when_the_order_has_none(world):
    contact = _partner(world)
    order = _sent_order(world)
    SupplierOrder.objects.filter(pk=order.pk).update(expected_date=None)
    _link, raw = _mint("supplier_order", order, contact)
    client = _verified(raw)
    assert client.post(f"{BASE}/act", {"token": raw, "action": "confirm"}, format="json").status_code == 422
    done = client.post(f"{BASE}/act", {"token": raw, "action": "confirm", "expected_date": _tomorrow()}, format="json")
    assert done.status_code == 200


def test_a_contact_without_the_right_cannot_confirm_or_answer(world):
    reader = _partner(world, can_act=False)
    order = _sent_order(world)
    _link, raw = _mint("supplier_order", order, reader)
    guest = _post("open", {"token": raw}).json()
    assert guest["decide"] == {"allowed": False, "reason": "no_right"}
    client = client_for(reader)
    response = client.post(
        f"{BASE}/act", {"token": raw, "action": "confirm", "expected_date": _tomorrow()}, format="json"
    )
    assert response.status_code == 403
    order.refresh_from_db()
    assert order.status == OrderStatus.SENT


def test_a_contact_without_the_products_module_cannot_act(world):
    contact = _partner(world, modules=("catalog_requests",))
    order = _sent_order(world)
    order.refresh_from_db()
    _link, raw = _mint("supplier_order", order, contact)
    client = client_for(contact)
    response = client.post(
        f"{BASE}/act", {"token": raw, "action": "confirm", "expected_date": _tomorrow()}, format="json"
    )
    assert response.status_code == 403
    assert SupplierOrder.objects.get(pk=order.pk).status == OrderStatus.SENT


def test_a_partner_is_never_made_a_client(world):
    contact = _partner(world)
    order = _sent_order(world)
    _link, raw = _mint("supplier_order", order, contact)
    _verified(raw)
    vendor = Company.objects.get(pk=world["vendor"].pk)
    assert not vendor.types.filter(code="CLIENT").exists()
    assert not CompanyRelationship.objects.filter(company=vendor, role="client").exists()


# ── Telegram: тот же путь ДК-4 ──────────────────────────────────────────────────────────────────────────────────────


def test_the_link_goes_to_the_linked_telegram_of_the_partner_contact(world):
    from integration.models import CrmClientMapping, CrmContactMapping
    from integration.tests import bus_support

    bus_support.reset()
    contact = _partner(world)
    Contact.objects.filter(pk=contact.pk).update(telegram_user_id=777)
    CrmClientMapping.objects.create(
        company=world["vendor"], crm_client_id=4343
    )  # партнёр, он же клиент CRM, — тогда бот достаёт
    CrmContactMapping.objects.create(contact=contact, crm_contact_id=58)
    order = _sent_order(world)
    _deliver_all("partner_order_sent")
    (envelope,) = bus_support.published("document_link.telegram_requested")
    bus_support.assert_matches_contract(envelope, secret_masked=True)
    payload = bus_support.real_data(envelope)["payload"]
    assert (
        payload["kind"] == "link" and payload["document_kind"] == "supplier_order" and payload["number"] == order.number
    )
    raw = _link_of(next(m for m in mail.outbox if m.to == [contact.email]))
    assert payload["url"] == f"http://cabinet.localhost/d/{raw}", "в бот уходит та же ссылка, что и в письмо"


# ── Отзыв: список и «Отозвать ссылку» у сотрудника ──────────────────────────────────────────────────────────────────


def test_staff_sees_and_revokes_the_links_of_this_order_only(world):
    contact = _partner(world)
    order = _sent_order(world)
    other = SupplierOrder.objects.get(pk=_order(world)["id"])
    other.status = OrderStatus.SENT
    other.save(update_fields=["status"])
    _l1, raw1 = _mint("supplier_order", order, contact)
    _l2, raw2 = _mint("supplier_order", order, contact)
    _l3, raw3 = _mint("supplier_order", other, contact)
    staff = api(world["supply"])
    listed = staff.get(f"{STOCK}orders/{order.pk}/partner-links/")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["links"]) == 2 and body["can_revoke"] is True
    assert all(row["recipient_hint"] == "d***@vendor.example" and row["state"] == "active" for row in body["links"])
    assert "dilshod" not in listed.content.decode()
    revoked = staff.post(f"{STOCK}orders/{order.pk}/revoke-partner-links/")
    assert revoked.status_code == 200 and revoked.json()["can_revoke"] is False
    assert {row["state"] for row in revoked.json()["links"]} == {"revoked"}
    assert _post("open", {"token": raw1}).status_code == 410 and _post("open", {"token": raw2}).status_code == 410
    assert _post("open", {"token": raw3}).status_code == 200, "ссылка другого заказа живая"
    assert order.log.filter(detail__contains="отозвана").exists()


def test_staff_revokes_the_links_of_a_price_request(world):
    contact = _partner(world)
    req = _request(world)
    _link, raw = _mint("price_request", req, contact)
    staff = api(world["supply"])
    assert len(staff.get(f"{STOCK}price-requests/{req.pk}/partner-links/").json()["links"]) == 1
    assert staff.post(f"{STOCK}price-requests/{req.pk}/revoke-partner-links/").status_code == 200
    assert _post("open", {"token": raw}).status_code == 410


@pytest.mark.parametrize("path", ["orders/{id}/partner-links/", "price-requests/{id}/partner-links/"])
def test_the_links_need_the_supply_right(world, path):
    order = _sent_order(world)
    url = STOCK + path.format(id=order.pk)
    assert api(world["reader"]).get(url).status_code == 403
    assert api(world["outsider"]).get(url).status_code == 403
    assert api(world["supply"]).get(STOCK + "orders/999999/partner-links/").status_code == 404
