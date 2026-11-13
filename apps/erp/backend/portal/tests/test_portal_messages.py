"""Чат кабинета (CHAT-1, ADR-0023): `GET/POST /messages`, `POST /messages/read`, `Me.unread`, проекция ответов CRM.

Компания и автор — из сессии; метка документа — только своей компании (чужая — 404); сообщение и событие
`erp.cabinet.message_posted` — одна транзакция; повтор `client_message_id` — без дубля; ответ менеджера
(`crm.cabinet.message_sent`) идемпотентен; обезличивание лида беседы стирает ленту и не даёт опоздавшему ответу её вернуть.
Изоляция компаний — негативными тестами на каждый эндпоинт.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.conf import settings as dj_settings
from django.utils import timezone
from integration.models import CrmClientMapping, CrmContactMapping
from integration.tests import bus_support
from parties.models import Company, CompanyRelationship, CompanyType, Contact, RelationshipRole, RelationshipStatus
from portal.models import PortalChatReader, PortalMessage
from portal.services import messages as chat
from portal.services.roles import ROLE_DEFAULT_MODULES
from portal.tests.conftest import PortalAPIClient, make_portal_session
from portal.tests.contract_support import check_response, response_schema
from rt_bus.django.models import Outbox

from crm.constants import ActStatusCode, InvoiceStatusCode
from crm.models import Act, ActStatus, Deal, Invoice, InvoiceStatus

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
POSTED = chat.POSTED_TYPE


def posted_events() -> list[dict]:
    return [row.envelope for row in Outbox.objects.filter(type=POSTED).order_by("created_at", "id")]


def send(client, text="Когда будет счёт?", key="cm_0000000001", context=None):
    body = {"text": text, "client_message_id": key}
    if context is not None:
        body["context"] = context
    return client.post(f"{API}/messages", body, format="json")


def reply(company, message_id=501, text="Счёт сегодня", sent_at=None):
    return chat.apply_manager_reply(
        {
            "message_id": message_id,
            "crm_lead_id": 7,
            "crm_client_id": None,
            "erp_company_id": company.pk,
            "text": text,
            "manager_name": "Илья Смирнов",
            "sent_at": (sent_at or timezone.now()).isoformat(),
            "actor": {"type": "staff", "crm_user_id": 3},
        }
    )


def client_for(session) -> PortalAPIClient:
    client = PortalAPIClient()
    client.cookies[dj_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


# ── Отправка и лента ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_post_writes_the_message_and_the_event_in_one_go(portal_client, client_company, client_contact):
    response = send(portal_client)

    assert response.status_code == 201, response.content
    assert check_response(response.json(), response_schema("/messages", "post", "201")) == []
    body = response.json()
    assert body["direction"] == "client" and body["mine"] is True
    assert body["author_name"] == client_contact.name
    (envelope,) = posted_events()
    bus_support.assert_matches_contract(envelope)
    data = envelope["data"]
    assert data["erp_company_id"] == client_company.pk
    assert data["crm_client_id"] is None  # компания ещё не сопоставлена — сообщение всё равно уходит
    assert data["payload"]["author"] == {
        "erp_contact_id": client_contact.pk,
        "crm_contact_id": None,
        "name": client_contact.name,
    }
    assert data["payload"]["erp_message_id"] == body["id"]
    assert envelope["subject"] == f"company/{client_company.pk}"


def test_mapped_company_and_contact_carry_their_crm_ids(portal_client, client_company, client_contact):
    CrmClientMapping.objects.create(crm_client_id=42, company=client_company)
    CrmContactMapping.objects.create(crm_contact_id=58, contact=client_contact)
    assert send(portal_client).status_code == 201
    (envelope,) = posted_events()
    assert envelope["data"]["crm_client_id"] == 42
    assert envelope["data"]["payload"]["author"]["crm_contact_id"] == 58


def test_a_repeat_with_the_same_key_returns_the_same_message_without_a_second_event(portal_client):
    first = send(portal_client)
    again = send(portal_client)  # новый Idempotency-Key, тот же client_message_id

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert PortalMessage.objects.count() == 1
    assert len(posted_events()) == 1


def test_the_message_is_not_kept_when_the_event_is_not_written(portal_client, monkeypatch):
    """Outbox в той же транзакции: публикация упала — строки ленты нет (и 500, а не тихий успех)."""
    from integration import bus

    def broken(*args, **kwargs):
        raise RuntimeError("outbox is down")

    monkeypatch.setattr(bus.get_bus(), "publish", broken)
    portal_client.raise_request_exception = False
    response = send(portal_client)

    assert response.status_code == 500
    assert PortalMessage.objects.count() == 0
    assert posted_events() == []


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"text": "   ", "client_message_id": "cm_0000000001"}, "TEXT_REQUIRED"),
        ({"text": "x" * 4001, "client_message_id": "cm_0000000001"}, "VALIDATION_ERROR"),
        ({"text": "Привет", "client_message_id": "short"}, "VALIDATION_ERROR"),
        (
            {"text": "Привет", "client_message_id": "cm_0000000001", "context": {"kind": "order", "id": 1}},
            "VALIDATION_ERROR",
        ),
    ],
)
def test_invalid_messages_are_refused(portal_client, body, code):
    response = portal_client.post(f"{API}/messages", body, format="json")
    assert response.status_code == 422
    assert response.json()["detail"] == code
    assert PortalMessage.objects.count() == 0


def test_text_is_kept_as_typed_and_returned_as_text(portal_client):
    text = '<img src=x onerror="alert(1)"> и\nперенос'
    assert send(portal_client, text=text).status_code == 201
    (item,) = portal_client.get(f"{API}/messages").json()["items"]
    assert item["text"] == text


def test_feed_is_ascending_and_after_id_returns_only_newer(portal_client, client_company):
    send(portal_client, text="Первое", key="cm_0000000001")
    reply(client_company, 501, "Ответ")
    send(portal_client, text="Третье", key="cm_0000000003")

    response = portal_client.get(f"{API}/messages")
    assert check_response(response.json(), response_schema("/messages", "get")) == []
    items = response.json()["items"]
    assert [i["text"] for i in items] == ["Первое", "Ответ", "Третье"]
    assert [i["direction"] for i in items] == ["client", "manager", "client"]
    assert items[1]["author_name"] == "Илья Смирнов" and items[1]["mine"] is False

    newer = portal_client.get(f"{API}/messages", {"after_id": items[0]["id"]}).json()
    assert [i["text"] for i in newer["items"]] == ["Ответ", "Третье"]
    page = portal_client.get(f"{API}/messages", {"limit": 2}).json()
    assert [i["text"] for i in page["items"]] == ["Ответ", "Третье"] and page["has_more"] is True


def test_colleagues_see_one_company_feed_and_mine_is_per_contact(portal_client, readonly_portal_client):
    send(portal_client)
    (item,) = readonly_portal_client.get(f"{API}/messages").json()["items"]
    assert item["mine"] is False


# ── Метка документа ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_context_of_an_own_document_gets_its_number_from_erp(contract_world, portal_client):
    quote = contract_world["quotes"]["sent"]
    response = send(portal_client, context={"kind": "quote", "id": quote.pk})

    assert response.status_code == 201, response.content
    context = response.json()["context"]
    assert context["kind"] == "quote" and context["id"] == quote.pk and context["number"]
    payload = posted_events()[0]["data"]["payload"]
    assert payload["context"] == {"kind": "quote", "erp_id": quote.pk, "number": context["number"]}


def test_context_of_an_own_deal_is_its_deal_ref(contract_world, portal_client):
    deal = contract_world["main"]
    response = send(portal_client, context={"kind": "deal", "id": deal.pk})
    assert response.json()["context"]["number"] == deal.number


def _foreign_documents(world) -> dict:
    """Сделка, КП, счёт и акт чужой компании, все видимые её контактам (выставлены)."""
    other_deal = world["other"]["deal"]
    invoice = Invoice.objects.create(
        deal=other_deal,
        number="INV-CHAT-other",
        status=InvoiceStatus.objects.get_or_create(code=InvoiceStatusCode.ISSUED, defaults={"name": "x"})[0],
        due_date=timezone.localdate() + datetime.timedelta(days=10),
        issued_at=timezone.localdate(),
        total_incl_vat=Decimal("1000"),
        currency=world["uzs"],
    )
    act = Act.objects.create(
        deal=other_deal,
        invoice=invoice,
        number="ACT-CHAT-other",
        status=ActStatus.objects.get_or_create(code=ActStatusCode.ISSUED, defaults={"name": "x"})[0],
        issued_at=timezone.localdate(),
        total_amount=Decimal("1000"),
    )
    return {"deal": other_deal, "quote": world["other"]["quote"], "invoice": invoice, "act": act}


@pytest.mark.parametrize("kind", ["deal", "quote", "invoice", "act"])
def test_context_of_another_company_is_404_without_a_trace(contract_world, portal_client, other_portal_client, kind):
    foreign = _foreign_documents(contract_world)[kind]
    if kind in ("invoice", "act"):  # документ действительно виден своей компании: 404 — из-за чужой сессии
        listed = other_portal_client.get(f"{API}/{kind}s").json()
        assert foreign.pk in {row["id"] for row in listed}
    before = PortalMessage.objects.count()
    response = send(portal_client, context={"kind": kind, "id": foreign.pk})

    assert response.status_code == 404
    assert foreign.__class__.__name__ not in response.content.decode()
    assert PortalMessage.objects.count() == before
    assert posted_events() == []


@pytest.mark.parametrize("kind", ["invoice", "act"])
def test_context_of_a_missing_document_is_404(contract_world, portal_client, kind):
    assert send(portal_client, context={"kind": kind, "id": 987654}).status_code == 404


@pytest.mark.parametrize(
    ("kind", "pick"),
    [
        ("quote", lambda w: w["hidden_quotes"]["sent_without_link"]),
        ("quote", lambda w: next(q for k, q in w["hidden_quotes"].items() if k != "sent_without_link")),
        ("invoice", lambda w: w["invoices"]["draft"]),
        ("invoice", lambda w: w["invoices"]["not_issued"]),
        ("act", lambda w: w["acts"]["draft"]),
    ],
)
def test_context_of_an_own_document_hidden_from_the_client_is_404(contract_world, portal_client, kind, pick):
    """Документ своей компании, которого клиент не видит в списках портала (черновик КП, счёт вне `client_invoices_q`,
    черновик акта), меткой не становится — тот же 404, номер не раскрывается."""
    hidden = pick(contract_world)
    before = PortalMessage.objects.count()
    response = send(portal_client, context={"kind": kind, "id": hidden.pk})
    assert response.status_code == 404
    if hidden.number:
        assert hidden.number not in response.content.decode()
    assert PortalMessage.objects.count() == before


def test_context_needs_the_module_of_the_document(contract_world):
    """Партнёрская сессия без «КП» и «Счетов» не ссылается на КП и счёт своей компании (не узнаёт их номер): 404; на
    заявку (сделку) — может, у неё «Каталог и заявки»."""
    supplier = Company.objects.create(name="OOO Partner Chat", inn="300000888")
    supplier.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})[0])
    contact = Contact.objects.create(company=supplier, name="Partner Chat", email="pc@partner.example", can_act=True)
    CompanyRelationship.objects.create(
        company=supplier, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE, modules=["catalog_requests"]
    )
    deal = contract_world["main"]
    Deal.objects.filter(pk=deal.pk).update(company=supplier)  # сделка, КП и счёт мира — теперь документы партнёра
    partner = client_for(make_portal_session(contact, supplier, "magic_link"))
    me = partner.get(f"{API}/me").json()
    assert "quotes" not in me["modules"] and "messages" in me["modules"]
    quote = contract_world["quotes"]["sent"]
    assert send(partner, key="cm_partner_q1", context={"kind": "quote", "id": quote.pk}).status_code == 404
    invoice = contract_world["invoices"]["issued"]
    assert send(partner, key="cm_partner_i1", context={"kind": "invoice", "id": invoice.pk}).status_code == 404
    response = send(partner, key="cm_partner_d1", context={"kind": "deal", "id": deal.pk})
    assert response.status_code == 201


# ── Права и модули ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_sending_needs_can_act_but_reading_and_marking_do_not(readonly_portal_client, client_company):
    reply(client_company)
    assert send(readonly_portal_client).status_code == 403
    feed = readonly_portal_client.get(f"{API}/messages")
    assert feed.status_code == 200
    last = feed.json()["items"][-1]["id"]
    assert readonly_portal_client.post(f"{API}/messages/read", {"last_id": last}, format="json").status_code == 200


def test_messages_module_is_on_for_clients_and_partners_and_not_toggled(client_type, portal_client):
    assert "messages" in portal_client.get(f"{API}/me").json()["modules"]
    supplier = Company.objects.create(name="OOO Supplier Chat", inn="300000777")
    supplier.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})[0])
    contact = Contact.objects.create(company=supplier, name="Partner Contact", email="p@supplier.example", can_act=True)
    # Сотрудник выключил партнёру всё, что можно выключить: «Сообщения», как и «Профиль», остаются
    CompanyRelationship.objects.create(
        company=supplier, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE, modules=[]
    )
    partner = client_for(make_portal_session(contact, supplier, "magic_link"))
    me = partner.get(f"{API}/me").json()
    assert me["roles"] == ["partner"] and "messages" in me["modules"]
    assert "messages" in ROLE_DEFAULT_MODULES["partner"]
    assert send(partner).status_code == 201


# ── Прочитанность и присутствие ──────────────────────────────────────────────────────────────────────────────────────


def test_unread_counts_manager_replies_after_the_read_mark(portal_client, client_company):
    send(portal_client)
    first = reply(client_company, 501)
    reply(client_company, 502)
    assert portal_client.get(f"{API}/me").json()["unread"] == 2

    response = portal_client.post(f"{API}/messages/read", {"last_id": first.pk}, format="json")
    assert check_response(response.json(), response_schema("/messages/read", "post")) == []
    assert response.json() == {"unread": 1}
    # отметка назад не уходит
    own = PortalMessage.objects.filter(direction="client").first()
    portal_client.post(f"{API}/messages/read", {"last_id": own.pk}, format="json")
    assert portal_client.get(f"{API}/me").json()["unread"] == 1


def test_polling_marks_presence_but_not_on_every_request(portal_client, client_company, client_contact):
    portal_client.get(f"{API}/messages")
    reader = PortalChatReader.objects.get(company=client_company, contact=client_contact)
    seen = reader.last_seen_at
    assert seen is not None
    portal_client.get(f"{API}/messages")
    reader.refresh_from_db()
    assert reader.last_seen_at == seen  # прореживание: не чаще PRESENCE_STEP
    later = seen + chat.PRESENCE_STEP + datetime.timedelta(seconds=1)
    chat.touch_presence(client_company, client_contact, now=later)
    reader.refresh_from_db()
    assert reader.last_seen_at == later


# ── Изоляция компаний ────────────────────────────────────────────────────────────────────────────────────────────────


def test_another_company_feed_is_not_readable(portal_client, other_portal_client):
    send(portal_client, text="Только для своей компании")
    assert other_portal_client.get(f"{API}/messages").json()["items"] == []


def test_unread_of_another_company_is_not_counted(portal_client, other_portal_client, other_company):
    reply(other_company, 601)
    assert other_portal_client.get(f"{API}/me").json()["unread"] == 1
    assert portal_client.get(f"{API}/me").json()["unread"] == 0


def test_read_mark_on_another_company_message_is_404(portal_client, other_portal_client, other_company, client_contact):
    foreign = reply(other_company, 601)
    response = portal_client.post(f"{API}/messages/read", {"last_id": foreign.pk}, format="json")

    assert response.status_code == 404
    assert not PortalChatReader.objects.filter(contact=client_contact, last_read_id__gt=0).exists()
    assert other_portal_client.get(f"{API}/me").json()["unread"] == 1


def test_the_same_key_in_another_company_is_another_message(portal_client, other_portal_client):
    assert send(portal_client, key="cm_shared_key_1").status_code == 201
    assert send(other_portal_client, key="cm_shared_key_1").status_code == 201
    assert PortalMessage.objects.count() == 2


# ── События CRM ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_manager_reply_is_idempotent(client_company):
    first = reply(client_company, 501)
    again = reply(client_company, 501)
    assert first.pk == again.pk
    assert PortalMessage.objects.filter(crm_message_id=501).count() == 1


def test_reply_to_an_unknown_company_is_skipped():
    ghost = Company(pk=999999)
    assert reply(ghost) is None
    assert PortalMessage.objects.count() == 0


def erased(company, scope, contact_ids=(), at=None):
    return chat.apply_lead_erased(
        {
            "crm_lead_id": 7,
            "crm_client_id": None,
            "erased_at": (at or timezone.now()).isoformat(),
            "actor": {"type": "bot"},
            "cabinet": {"erp_company_id": company.pk, "scope": scope, "erp_contact_ids": list(contact_ids)},
        }
    )


def test_erasing_a_person_erases_only_their_messages(
    portal_client, readonly_portal_client, client_company, client_contact, readonly_contact
):
    """Стирание контакта А (Slack, Intercom): его сообщения — «Удалённый пользователь» без текста; сообщения коллеги Б,
    ответ менеджера и сама лента компании остаются."""
    send(portal_client, text="Пишет А", key="cm_person_a_1")
    reply(client_company, 501, "Ответ менеджера")
    # коллега Б (контакт только для чтения) пишет из той же компании — строка ленты напрямую
    PortalMessage.objects.create(
        company=client_company,
        direction=PortalMessage.DIRECTION_CLIENT,
        author_contact=readonly_contact,
        author_name=readonly_contact.name,
        text="Пишет Б",
        client_message_id="cm_person_b_1",
    )

    assert erased(client_company, "authors", [client_contact.pk]) == 1

    items = portal_client.get(f"{API}/messages").json()["items"]
    assert [(i["text"], i["erased"], i["author_name"]) for i in items] == [
        ("", True, None),
        ("Ответ менеджера", False, "Илья Смирнов"),
        ("Пишет Б", False, readonly_contact.name),
    ]
    assert items[0]["mine"] is False  # автора больше нет
    assert check_response(portal_client.get(f"{API}/messages").json(), response_schema("/messages", "get")) == []
    assert reply(client_company, 502, "Новый ответ") is not None  # лента живёт дальше


def test_polling_reports_messages_erased_after_they_were_shown(
    portal_client, other_portal_client, client_company, client_contact, other_company, other_contact
):
    """CHAT-1b: опрос с `after_id` приносит только новые сообщения — стёртое по запросу автора уже показанное
    сообщение Cabinet узнаёт из `erased_ids` (своей компании и не новее `after_id`)."""
    # чужое стёртое сообщение — раньше своих (id меньше after_id): отсечь его может только фильтр компании
    foreign = send(other_portal_client, text="Чужая компания", key="cm_poll_o_001").json()
    first = send(portal_client, text="Пишет А", key="cm_poll_a_001").json()
    reply(client_company, 501, "Ответ")
    erased(client_company, "authors", [client_contact.pk])
    erased(other_company, "authors", [other_contact.pk])
    last = PortalMessage.objects.filter(company=client_company).order_by("-id").first().pk
    assert foreign["id"] < last

    polled = portal_client.get(f"{API}/messages", {"after_id": last}).json()
    assert polled["items"] == []
    assert polled["erased_ids"] == [first["id"]]
    assert foreign["id"] not in polled["erased_ids"]
    assert other_portal_client.get(f"{API}/messages", {"after_id": last}).json()["erased_ids"] == [foreign["id"]]
    assert check_response(polled, response_schema("/messages", "get")) == []
    earlier = portal_client.get(f"{API}/messages", {"after_id": first["id"] - 1}).json()
    assert earlier["erased_ids"] == []  # новее after_id — придёт в items с erased: true
    assert earlier["items"][0]["erased"] is True
    assert portal_client.get(f"{API}/messages").json()["erased_ids"] == []


def test_erasing_the_client_wipes_the_whole_feed_and_a_late_reply_does_not_bring_it_back(portal_client, client_company):
    before = timezone.now() - datetime.timedelta(minutes=5)
    send(portal_client)
    reply(client_company, 501, sent_at=before)
    at = timezone.now()

    assert erased(client_company, "company", at=at) == 2

    assert PortalMessage.objects.filter(company=client_company).count() == 0
    # опоздавший ответ, отправленный до стирания, ленту не восстанавливает; новый — ложится
    assert reply(client_company, 502, sent_at=before) is None
    assert reply(client_company, 503, sent_at=at + datetime.timedelta(seconds=1)) is not None
    assert portal_client.get(f"{API}/messages").json()["items"][0]["text"] == "Счёт сегодня"


def test_erasing_a_person_of_another_company_does_not_touch_this_feed(portal_client, other_company, client_contact):
    send(portal_client)
    assert erased(other_company, "authors", [client_contact.pk]) == 0
    assert PortalMessage.objects.get().erased is False


def test_erasure_of_a_lead_without_a_cabinet_conversation_keeps_the_feed(portal_client):
    send(portal_client)
    assert (
        chat.apply_lead_erased({"crm_lead_id": 7, "crm_client_id": None, "erased_at": timezone.now().isoformat()}) == 0
    )
    assert PortalMessage.objects.count() == 1


def test_bus_handlers_are_registered_for_the_chat_events():
    from integration import bus_handlers
    from rt_bus.handlers import default_registry

    for event_type, func in [
        ("uz.railtech.crm.cabinet.message_sent.v1", bus_handlers.on_cabinet_message_sent),
        ("uz.railtech.crm.lead.erased.v1", bus_handlers.on_lead_erased),
    ]:
        (handler,) = default_registry.match(event_type)
        assert handler.func is func
