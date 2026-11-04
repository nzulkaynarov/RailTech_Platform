"""Колокольчик кабинета и маршрутизатор уведомлений контрагента (NOTIFY-2, ADR-0023 п. 2, ADR-0008).

Что держат тесты:
1. источники — события ERP для контрагента пишут строку ленты на каждый действующий контакт; повтор события строк и писем не
   добавляет; группы, виды, объекты и действия — те же, что в контракте;
2. маршрутизатор — один внешний канал на событие и контакт: бот CRM уже шлёт (Telegram привязан, компания сопоставлена CRM) —
   ERP не дублирует; вид, который бот не шлёт, — письмом и контакту с Telegram; письмо КП уже ушло — второго нет;
3. лента портала — по убыванию, страницы, прочитанность по контакту, «прочитать все», счётчик в `/me`, изоляция компаний,
   контактов и модулей (чужое не читается и не помечается);
4. письмо — шаблон `portal_notice` на языке контакта (ru/uz/en), подвал «Настроить уведомления»; отложенное письмо (ответ
   менеджера) гасится прочтением и присутствием, повтор задачи второго письма не шлёт (мутационная проверка — в PR).
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from integration.models import CrmClientMapping
from parties.models import Contact
from portal.models import NoticeChannel, NoticeEmailState, PortalNotice
from portal.services import notice_sources, notices
from portal.tests.conftest import LOCMEM_BACKEND, PortalAPIClient, make_portal_session
from portal.tests.contract_support import component

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
CYRILLIC = re.compile("[А-Яа-яЁё]")


@pytest.fixture
def no_tg_contact(client_company):
    """Контакт без Telegram, приглашённый в кабинет: внешний канал у него — письмо."""
    return Contact.objects.create(
        company=client_company,
        name="Nodira Accountant",
        email="nodira@client.example",
        can_act=True,
        language="uz",
        invited_at=timezone.now(),
    )


@pytest.fixture
def crm_mapped(client_company):
    return CrmClientMapping.objects.create(crm_client_id=7001, company=client_company)


@pytest.fixture
def enqueued(monkeypatch):
    """Письма уведомлений, поставленные в очередь после коммита (id строк ленты)."""
    from portal import tasks

    sent: list[int] = []
    monkeypatch.setattr(tasks.send_notice_email, "delay", lambda notice_id: sent.append(notice_id))
    return sent


def _notify(company, kind="invoice_issued", dedup="1", object_id=1, **extra):
    extra.setdefault("link", "/invoices?focus=1")
    return notices.notify(kind, company=company, object_id=object_id, object_number="INV-1", dedup=dedup, **extra)


def _by_contact(rows):
    return {row.contact_id: row for row in rows}


def client_for(session):
    from django.conf import settings

    client = PortalAPIClient()
    client.cookies[settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    return client


# ── 0. Перечни совпадают с контрактом ───────────────────────────────────────────────────────────────────────────────


def test_kinds_groups_objects_and_actions_match_the_contract():
    assert set(notices.KINDS) == set(component("NotificationKind")["enum"])
    assert set(notices.GROUPS) == set(component("NotificationGroup")["enum"])
    assert {kind.group for kind in notices.KINDS.values()} == set(notices.GROUPS)
    assert {kind.object_type for kind in notices.KINDS.values()} == set(component("NotificationObjectType")["enum"])
    assert {kind.action for kind in notices.KINDS.values()} == set(component("NotificationAction")["enum"])


# ── 1. Маршрутизатор: один канал на событие и контакт ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "telegram", "email", "bot_reaches", "emailed", "expected"),
    [
        ("invoice_issued", 1, "a@x.example", True, set(), NoticeChannel.TELEGRAM),  # бот уже шлёт — ERP молчит
        ("invoice_issued", None, "a@x.example", True, set(), NoticeChannel.EMAIL),  # Telegram нет — письмо
        ("invoice_issued", 1, "a@x.example", False, set(), NoticeChannel.EMAIL),  # компания не в CRM — бот не узнает
        ("payment_overdue", 1, "a@x.example", True, set(), NoticeChannel.EMAIL),  # бот этот вид не шлёт — письмо
        ("partner_card_returned", 1, "a@x.example", True, set(), NoticeChannel.EMAIL),
        ("manager_replied", None, "a@x.example", True, set(), NoticeChannel.EMAIL_DELAYED),
        ("delivery_status_changed", None, "a@x.example", True, set(), NoticeChannel.CABINET),  # не важное
        ("quote_sent", None, "A@X.example", False, {"a@x.example"}, NoticeChannel.SOURCE),  # письмо КП уже ушло
        ("act_issued", None, "", True, set(), NoticeChannel.CABINET),  # писать некуда
    ],
)
def test_router_picks_one_channel(kind, telegram, email, bot_reaches, emailed, expected):
    contact = Contact(name="X", email=email, telegram_user_id=telegram, invited_at=timezone.now())
    channel, _reason = notices.choose_channel(
        notices.KINDS[kind], contact, bot_reaches=bot_reaches, already_emailed=emailed
    )
    assert channel == expected


@pytest.mark.parametrize(
    ("email", "invited", "logged_in", "document", "expected"),
    [
        ("a@x.example", True, False, False, (NoticeChannel.EMAIL, "")),  # приглашён
        ("a@x.example", False, True, False, (NoticeChannel.EMAIL, "")),  # уже входил
        ("a@x.example", False, False, True, (NoticeChannel.EMAIL, "")),  # контакт документа (сделки, получатель КП)
        ("a@x.example", False, False, False, (NoticeChannel.CABINET, "not_invited")),  # сначала — приглашение
        ("not-an-address", True, False, True, (NoticeChannel.CABINET, "invalid_email")),  # неверный адрес — сразу
        ("", True, False, True, (NoticeChannel.CABINET, "no_email")),
    ],
)
def test_email_goes_only_to_document_or_invited_contacts(email, invited, logged_in, document, expected):
    """Решение лида по #402 (Odoo portal — подписчики документа, HubSpot — контакты с доступом): колокольчик — всем,
    письмо — контакту документа и приглашённым или входившим; неприглашённому первым письмом придёт приглашение."""
    contact = Contact(
        pk=501,
        name="X",
        email=email,
        invited_at=timezone.now() if invited else None,
        last_login_at=timezone.now() if logged_in else None,
    )
    got = notices.choose_channel(
        notices.KINDS["invoice_issued"],
        contact,
        bot_reaches=True,
        already_emailed=set(),
        document_contact_ids=(501,) if document else (),
    )
    assert got == expected


def test_not_invited_colleague_gets_the_bell_but_no_email(client_company, client_contact, enqueued):
    stranger = Contact.objects.create(company=client_company, name="Not Invited", email="nobody@client.example")
    rows = _by_contact(_notify(client_company, dedup="stranger"))
    assert rows[stranger.pk].channel == NoticeChannel.CABINET
    assert rows[stranger.pk].email_reason == "not_invited"


# ── 2. Источники: событие → строка ленты на контакт, идемпотентно ────────────────────────────────────────────────────


def test_invoice_issued_reaches_every_contact_once(
    contract_world,
    client_contact,
    readonly_contact,
    no_tg_contact,
    crm_mapped,
    enqueued,
    django_capture_on_commit_callbacks,
):
    from integration.services import events

    invoice = contract_world["invoices"]["partially_paid"]
    with django_capture_on_commit_callbacks(execute=True):
        events.publish_invoice_event("invoice.issued", invoice)
        events.publish_invoice_event("invoice.issued", invoice)  # повтор события

    rows = PortalNotice.objects.filter(kind="invoice_issued", object_id=invoice.pk)
    assert rows.count() == 3, "строка на каждый контакт и ни одной лишней"
    by = _by_contact(rows)
    assert by[client_contact.pk].channel == NoticeChannel.TELEGRAM  # бот CRM уже шлёт — ERP не дублирует
    assert by[readonly_contact.pk].channel == NoticeChannel.TELEGRAM
    assert by[no_tg_contact.pk].channel == NoticeChannel.EMAIL
    assert enqueued == [by[no_tg_contact.pk].pk], "письмо — только контакту без Telegram, и одно"
    row = by[no_tg_contact.pk]
    assert (row.group, row.object_type, row.action) == ("money", "invoice", "issued")
    assert row.link == f"/invoices?focus={invoice.pk}"
    assert row.params["number"] == invoice.number and row.params["currency"] == "UZS"


def test_company_without_crm_mapping_gets_email_even_with_telegram(
    contract_world, client_contact, enqueued, django_capture_on_commit_callbacks
):
    """События на шине нет (компания не сопоставлена клиенту CRM) — бот не напишет, поэтому письмо."""
    from integration.services import events

    act = contract_world["acts"]["accepted"]
    with django_capture_on_commit_callbacks(execute=True):
        assert events.publish_act_event("act.issued", act) is None
    row = PortalNotice.objects.get(kind="act_issued", object_id=act.pk, contact=client_contact)
    assert row.channel == NoticeChannel.EMAIL and row.action == "awaiting_acceptance"
    assert row.pk in enqueued


def test_overdue_payment_is_emailed_to_contacts_with_telegram_too(
    contract_world, client_contact, crm_mapped, enqueued, django_capture_on_commit_callbacks
):
    from integration.services import events

    invoice = contract_world["invoices"]["overdue"]
    PortalNotice.objects.filter(kind="payment_overdue").delete()
    with django_capture_on_commit_callbacks(execute=True):
        events.publish_invoice_event("invoice.overdue", invoice)
    row = PortalNotice.objects.get(kind="payment_overdue", contact=client_contact)
    assert row.channel == NoticeChannel.EMAIL, "бот о просрочке не пишет — уведомление не теряется"
    assert row.pk in enqueued


def test_quote_sent_does_not_repeat_the_quote_email(contract_world, client_contact, no_tg_contact, enqueued):
    """Письмо с КП получателю КП уже уходит (ERP-11): ему второе не шлём; коллеге без Telegram — уведомление письмом."""
    quote = contract_world["quotes"]["viewed"]
    notice_sources.quote_sent(quote, channels=["email"])
    by = _by_contact(PortalNotice.objects.filter(kind="quote_sent", object_id=quote.pk))
    assert by[client_contact.pk].channel == NoticeChannel.SOURCE  # получатель КП — контакт сделки
    assert by[no_tg_contact.pk].channel == NoticeChannel.EMAIL
    assert by[client_contact.pk].link == f"/quotes/{quote.pk}"
    # переотправка той же версии — без новых строк
    notice_sources.quote_sent(quote, channels=["telegram"])
    assert PortalNotice.objects.filter(kind="quote_sent", object_id=quote.pk).count() == 2


def test_delivery_status_is_bell_only_and_client_decisions_are_not_echoed(contract_world, client_contact, enqueued):
    shipped = contract_world["deliveries"]["in_transit"]
    notice_sources.delivery_status_changed(shipped, "in_transit")
    row = PortalNotice.objects.get(kind="delivery_status_changed", object_id=shipped.deal_id, contact=client_contact)
    assert (
        row.object_type == "delivery" and row.object_number == f"D-{shipped.deal_id}"
    )  # id — сделки, как в start_param
    assert row.channel == NoticeChannel.CABINET and row.email_state == ""
    assert row.link == f"/deals/{shipped.deal_id}"
    accepted = contract_world["deliveries"]["accepted"]
    notice_sources.delivery_status_changed(accepted, "delivered")
    assert not PortalNotice.objects.filter(object_id=accepted.deal_id, kind="delivery_status_changed").exists()


def test_eta_shift_is_important(
    contract_world, no_tg_contact, crm_mapped, enqueued, django_capture_on_commit_callbacks
):
    fulfillment = contract_world["deliveries"]["shipped"]
    previous = fulfillment.expected_delivery_date
    fulfillment.expected_delivery_date = previous + timedelta(days=5)
    fulfillment.save(update_fields=["expected_delivery_date", "updated_at"])
    with django_capture_on_commit_callbacks(execute=True):
        notice_sources.delivery_eta_changed(fulfillment, previous)
        notice_sources.delivery_eta_changed(fulfillment, previous)  # повтор того же события
    row = PortalNotice.objects.get(kind="delivery_eta_changed", contact=no_tg_contact, object_id=fulfillment.deal_id)
    assert row.channel == NoticeChannel.EMAIL
    assert row.params["previous_eta"] == previous.isoformat()
    assert enqueued.count(row.pk) == 1


def _save_change(fulfillment, **fields):
    """Одно изменение поставки: новое время сохранения строки исполнения (как `update_fulfillment_status`)."""
    for name, value in fields.items():
        setattr(fulfillment, name, value)
    fulfillment.updated_at = timezone.now() + timedelta(microseconds=1)
    fulfillment.save(update_fields=[*fields, "updated_at"])


def test_eta_back_and_forth_is_a_notice_per_change(contract_world, no_tg_contact, enqueued):
    """Ключ — от изменения, а не от значения: A → B → A → B — три уведомления (третий переход по значению совпадает с
    первым); повтор вызова без нового сохранения строку не добавляет."""
    fulfillment = contract_world["deliveries"]["in_transit"]
    a = fulfillment.expected_delivery_date
    b = a + timedelta(days=7)
    for previous, new in ((a, b), (b, a), (a, b)):
        _save_change(fulfillment, expected_delivery_date=new)
        notice_sources.delivery_eta_changed(fulfillment, previous)
        notice_sources.delivery_eta_changed(fulfillment, previous)  # повтор того же события
    rows = PortalNotice.objects.filter(
        kind="delivery_eta_changed", contact=no_tg_contact, object_id=fulfillment.deal_id
    )
    assert [row.params["eta"] for row in rows.order_by("pk")] == [b.isoformat(), a.isoformat(), b.isoformat()]


def test_delivery_status_back_and_forth_is_a_notice_per_change(contract_world, no_tg_contact):
    """Статус X → Y → X — три уведомления; повтор вызова без нового сохранения — нет."""
    from sales.models import FulfillmentStatus

    fulfillment = contract_world["deliveries"]["shipped"]
    shipped, in_transit = (FulfillmentStatus.objects.get(code=code) for code in ("SHIPPED", "IN_TRANSIT"))
    for status, code in ((in_transit, "in_transit"), (shipped, "shipped"), (in_transit, "in_transit")):
        _save_change(fulfillment, status=status)
        notice_sources.delivery_status_changed(fulfillment, code)
        notice_sources.delivery_status_changed(fulfillment, code)
    rows = PortalNotice.objects.filter(
        kind="delivery_status_changed", contact=no_tg_contact, object_id=fulfillment.deal_id
    )
    assert [row.params["status"] for row in rows.order_by("pk")] == ["in_transit", "shipped", "in_transit"]


def test_archived_contacts_and_closed_companies_get_nothing(client_company, client_contact, no_tg_contact):
    no_tg_contact.archived_at = timezone.now()
    no_tg_contact.save(update_fields=["archived_at"])
    rows = _notify(client_company)
    assert [row.contact_id for row in rows] == [client_contact.pk]
    type(client_company).objects.filter(pk=client_company.pk).update(is_active=False)  # архив — кабинет закрыт
    assert _notify(client_company, dedup="2") == []


def test_rollback_leaves_neither_notice_nor_email(client_company, client_contact, enqueued):
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            _notify(client_company, dedup="rollback")
            raise RuntimeError("откат")
    assert not PortalNotice.objects.filter(dedup_key="invoice_issued:rollback").exists()
    assert enqueued == []


# ── 3. Лента портала ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_feed_is_newest_first_with_pages(portal_client, client_company, client_contact):
    for n in range(5):
        _notify(client_company, dedup=f"page-{n}", object_id=n + 1)
    first = portal_client.get(f"{API}/notifications?limit=2").json()
    assert first["has_more"] is True
    ids = [item["id"] for item in first["items"]]
    assert ids == sorted(ids, reverse=True)
    rest = portal_client.get(f"{API}/notifications?limit=10&before_id={ids[-1]}").json()
    assert rest["has_more"] is False and len(rest["items"]) == 3
    item = first["items"][0]
    assert item["object"] == {"type": "invoice", "id": 5, "number": "INV-1"}
    assert item["read_at"] is None and item["text_key"] == "invoice_issued"


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "limit=x", "before_id=0"])
def test_bad_page_params_are_422(portal_client, query):
    response = portal_client.get(f"{API}/notifications?{query}")
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}


def test_unread_counter_read_by_ids_and_read_all(portal_client, client_company, client_contact):
    rows = [_notify(client_company, dedup=f"r-{n}", object_id=n + 1)[0] for n in range(3)]
    assert portal_client.get(f"{API}/me").json()["notifications_unread"] == 3
    response = portal_client.post(f"{API}/notifications/read", {"ids": [rows[0].pk]}, format="json")
    assert response.status_code == 200 and response.json() == {"unread": 2}
    assert portal_client.get(f"{API}/me").json()["notifications_unread"] == 2
    assert portal_client.post(f"{API}/notifications/read", {"all": True}, format="json").json() == {"unread": 0}
    assert PortalNotice.objects.filter(contact=client_contact, read_at__isnull=True).count() == 0


@pytest.mark.parametrize("body", [{}, {"ids": [1], "all": True}, {"all": False}, {"ids": []}, {"ids": [1], "x": 1}])
def test_read_mark_needs_exactly_one_of_ids_or_all(portal_client, body):
    response = portal_client.post(f"{API}/notifications/read", body, format="json")
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}


def test_readonly_contact_can_mark_read(readonly_portal_client, client_company, readonly_contact):
    """Прочтение — не действие за компанию: `can_act` не нужен."""
    row = _notify(client_company, dedup="ro")
    mine = next(r for r in row if r.contact_id == readonly_contact.pk)
    response = readonly_portal_client.post(f"{API}/notifications/read", {"ids": [mine.pk]}, format="json")
    assert response.status_code == 200 and response.json() == {"unread": 0}


def test_other_company_notices_are_neither_listed_nor_marked(
    portal_client, client_company, client_contact, other_company, other_contact
):
    theirs = _notify(other_company, dedup="theirs")[0]
    mine = _notify(client_company, dedup="mine")
    listed = {item["id"] for item in portal_client.get(f"{API}/notifications").json()["items"]}
    assert theirs.pk not in listed and {r.pk for r in mine if r.contact_id == client_contact.pk} == listed
    portal_client.post(f"{API}/notifications/read", {"ids": [theirs.pk]}, format="json")
    portal_client.post(f"{API}/notifications/read", {"all": True}, format="json")
    theirs.refresh_from_db()
    assert theirs.read_at is None, "чужое уведомление не помечается ни по id, ни «прочитать все»"


def test_colleague_notices_are_private(portal_client, client_company, client_contact, readonly_contact):
    """Строка — на контакт: коллега видит и читает своё, прочтение одного не гасит другому."""
    rows = _by_contact(_notify(client_company, dedup="colleague"))
    colleague = rows[readonly_contact.pk]
    listed = {item["id"] for item in portal_client.get(f"{API}/notifications").json()["items"]}
    assert colleague.pk not in listed
    assert portal_client.post(f"{API}/notifications/read", {"ids": [colleague.pk]}, format="json").json() == {
        "unread": 1
    }
    colleague.refresh_from_db()
    assert colleague.read_at is None
    portal_client.post(f"{API}/notifications/read", {"all": True}, format="json")
    colleague.refresh_from_db()
    assert colleague.read_at is None


def test_contact_moved_to_another_company_does_not_see_old_notices(client_company, client_contact, other_company):
    _notify(client_company, dedup="moved")
    session = make_portal_session(client_contact, client_company, "telegram")
    Contact.objects.filter(pk=client_contact.pk).update(company=other_company)
    assert client_for(session).get(f"{API}/notifications").status_code == 401


def test_feed_and_counter_follow_session_modules(supplier_partner):
    """Партнёру без модуля счетов уведомления о счёте не видны и не считаются; карточка партнёра — видна."""
    company, contact, client = supplier_partner
    PortalNotice.objects.create(
        company=company,
        contact=contact,
        kind="invoice_issued",
        group="money",
        object_type="invoice",
        object_id=1,
        action="issued",
        text_key="invoice_issued",
        link="/invoices",
        dedup_key="x:1",
    )
    card = PortalNotice.objects.create(
        company=company,
        contact=contact,
        kind="partner_card_returned",
        group="partner_products",
        object_type="partner_product",
        object_id=9,
        object_number="Болт М12",
        action="returned",
        text_key="partner_card_returned",
        link="/my-products?card=9",
        dedup_key="x:2",
    )
    body = client.get(f"{API}/notifications").json()
    assert [item["id"] for item in body["items"]] == [card.pk]
    assert client.get(f"{API}/me").json()["notifications_unread"] == 1
    assert client.post(f"{API}/notifications/read", {"all": True}, format="json").json() == {"unread": 0}
    assert (
        PortalNotice.objects.get(kind="invoice_issued").read_at is None
    ), "невидимое модулям «прочитать все» не трогает"


@pytest.fixture
def supplier_partner(db):
    from parties.models import Company, CompanyRelationship, CompanyType, RelationshipRole, RelationshipStatus

    company = Company.objects.create(name="OOO Partner Bell", inn="300000777")
    company.types.add(CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик"})[0])
    CompanyRelationship.objects.create(
        company=company, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE, modules=["my_products"]
    )
    contact = Contact.objects.create(company=company, name="Partner", email="p@partner.example", can_act=True)
    return company, contact, client_for(make_portal_session(contact, company, "magic_link"))


# ── 4. Письмо по уведомлению ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def locmem(settings):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "https://cabinet.example.test"
    mail.outbox.clear()
    return mail.outbox


@pytest.mark.parametrize("language", ["ru", "uz", "en"])
@pytest.mark.parametrize(
    "kind",
    [
        "invoice_issued",
        "payment_overdue",
        "act_issued",
        "quote_sent",
        "delivery_eta_changed",
        "manager_replied",
        "partner_card_returned",
        "partner_card_published",
    ],
)
def test_email_is_in_the_contact_language_with_settings_footer(locmem, client_company, no_tg_contact, kind, language):
    no_tg_contact.language = language
    no_tg_contact.name = "Nodira"
    no_tg_contact.save(update_fields=["language", "name"])
    client_company.name = "Acme Trading"
    client_company.save(update_fields=["name"])
    params = {
        "number": "INV-7",
        "amount": "1200.00",
        "currency": "UZS",
        "due_date": "2026-11-20",
        "deal": "D-5",
        "eta": "2026-12-01",
        "previous_eta": "2026-11-25",
    }
    row = notices.notify(
        kind,
        company=client_company,
        object_id=7,
        object_number="INV-7",
        params=params,
        link="/invoices?focus=7",
        dedup="mail",
        bot_reaches=True,
    )
    row = next(r for r in row if r.contact_id == no_tg_contact.pk)
    _due_now(row)  # отложенное (ответ менеджера) — срок наступил
    assert notices.deliver_email(row.pk) == "sent"
    assert len(locmem) == 1
    message = locmem[0]
    assert message.to == ["nodira@client.example"]
    html = message.alternatives[0][0]
    for body in (message.body, html):
        assert "https://cabinet.example.test/invoices?focus=7" in body
        assert "https://cabinet.example.test/profile#notifications" in body, "подвал «Настроить уведомления»"
    if language != "ru":
        assert not CYRILLIC.search(message.subject), message.subject
        assert not CYRILLIC.search(message.body), message.body
    row.refresh_from_db()
    assert row.email_state == NoticeEmailState.SENT and row.email_sent_at is not None


def test_repeated_task_does_not_send_twice(locmem, client_company, no_tg_contact):
    """Повтор задачи (ретрай Celery, сборщик и задача после коммита одновременно) второго письма не шлёт.

    Мутационная проверка (PR): без отбора `email_state=PENDING` под блокировкой строки в `deliver_email` тест краснеет —
    уходят два письма.
    """
    row = next(r for r in _notify(client_company, dedup="twice") if r.contact_id == no_tg_contact.pk)
    assert notices.deliver_email(row.pk) == "sent"
    assert notices.deliver_email(row.pk) == "skipped"
    assert sum(notices.send_due_emails().values()) == 0
    assert len(locmem) == 1


def _delayed(company, contact):
    rows = notices.notify("manager_replied", company=company, object_id=1, link="/messages", dedup="reply-1")
    return next(r for r in rows if r.contact_id == contact.pk)


def test_delayed_email_waits_then_goes_if_unread(locmem, client_company, no_tg_contact):
    row = _delayed(client_company, no_tg_contact)
    assert row.channel == NoticeChannel.EMAIL_DELAYED
    assert row.email_due_at - row.created_at >= timedelta(minutes=10) - timedelta(seconds=1)
    assert notices.deliver_email(row.pk) == "not_due"
    assert notices.send_due_emails()["sent"] == 0
    PortalNotice.objects.filter(pk=row.pk).update(email_due_at=timezone.now() - timedelta(seconds=1))
    assert notices.send_due_emails()["sent"] == 1
    assert notices.send_due_emails()["sent"] == 0, "повтор сборщика второго письма не шлёт"
    assert len(locmem) == 1


def test_reading_in_the_bell_cancels_the_delayed_email(locmem, client_company, no_tg_contact):
    row = _delayed(client_company, no_tg_contact)
    notices.mark_read(no_tg_contact, client_company, ["profile", "messages"], ids=[row.pk])
    PortalNotice.objects.filter(pk=row.pk).update(email_due_at=timezone.now() - timedelta(seconds=1))
    assert notices.send_due_emails()["sent"] == 0
    row.refresh_from_db()
    assert row.email_state == NoticeEmailState.CANCELLED
    assert locmem == []


def test_presence_cancels_the_delayed_email(locmem, client_company, no_tg_contact):
    """Контакт заходил в кабинет после ответа — письмо не нужно (ADR-0023: «контакт в кабинете — только кабинет»)."""
    row = _delayed(client_company, no_tg_contact)
    Contact.objects.filter(pk=no_tg_contact.pk).update(last_login_at=timezone.now() + timedelta(seconds=1))
    PortalNotice.objects.filter(pk=row.pk).update(email_due_at=timezone.now() - timedelta(seconds=1))
    assert notices.deliver_email(row.pk) == "cancelled"
    assert locmem == []


def test_due_sweeper_task_is_scheduled():
    from core.celery import app

    assert app.conf.beat_schedule["portal.send_due_notice_emails"]["schedule"] == 60.0


@override_settings(EMAIL_BACKEND=LOCMEM_BACKEND)
def test_archived_contact_email_is_cancelled(client_company, no_tg_contact):
    row = next(r for r in _notify(client_company, dedup="arch") if r.contact_id == no_tg_contact.pk)
    Contact.objects.filter(pk=no_tg_contact.pk).update(archived_at=timezone.now())
    assert notices.deliver_email(row.pk) == "cancelled"


def test_act_reminder_is_a_new_bell_item_and_email(
    contract_world, no_tg_contact, enqueued, django_capture_on_commit_callbacks
):
    """«Напомнить» исполнителя: новая строка ленты и письмо; бот о напоминании не пишет — событие шины не публикуется."""
    act = contract_world["acts"]["issued"]
    act.reminder_sent_at = timezone.now()
    act.save(update_fields=["reminder_sent_at"])
    with django_capture_on_commit_callbacks(execute=True):
        notice_sources.act_issued(act, reminder=True)
        notice_sources.act_issued(act, reminder=True)
    reminder = PortalNotice.objects.get(
        kind="act_issued", object_id=act.pk, contact=no_tg_contact
    )  # повтор — без второй
    assert reminder.params["reminder"] == "1" and reminder.channel == NoticeChannel.EMAIL
    reminders = PortalNotice.objects.filter(kind="act_issued", object_id=act.pk, params__reminder="1")
    by = _by_contact(reminders)
    deal_contact = act.deal.contact_id
    assert (
        by[deal_contact].channel == NoticeChannel.EMAIL
    ), "контакту сделки с Telegram — тоже письмо: бот не напоминает"
    emailed = [row.pk for row in reminders if row.channel == NoticeChannel.EMAIL]
    assert sorted(enqueued) == sorted(emailed)
    issued = PortalNotice.objects.filter(kind="act_issued", object_id=act.pk, params__reminder="")
    assert issued.exists(), "напоминание — отдельная строка рядом с выставлением, а не замена"


# ── 5. Каждая защита письма — отдельно (мутационная проверка в PR) ────────────────────────────────────────────────────


def test_mark_read_cancels_the_pending_email_at_once(client_company, no_tg_contact):
    """Защита 1: прочтение сразу переводит письмо в `cancelled` (сборщик строку больше не берёт)."""
    row = _delayed(client_company, no_tg_contact)
    notices.mark_read(no_tg_contact, client_company, ["profile", "messages"], ids=[row.pk])
    row.refresh_from_db()
    assert row.email_state == NoticeEmailState.CANCELLED and row.email_reason == "read"


def test_delivery_rechecks_read_at_under_the_lock(locmem, client_company, no_tg_contact):
    """Защита 2: прочтение, записанное мимо `mark_read` (гонка с задачей), всё равно гасит письмо при отправке."""
    row = _delayed(client_company, no_tg_contact)
    PortalNotice.objects.filter(pk=row.pk).update(
        read_at=timezone.now(), email_due_at=timezone.now() - timedelta(seconds=1)
    )
    assert notices.deliver_email(row.pk) == "cancelled"
    assert locmem == []


# ── 6. Сбой одной строки не держит очередь ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def flaky_mail(monkeypatch, locmem):
    """Почта не принимает письма на `bounce@…` (как `EmailDeliveryError` передачи) и падает на `crash@…`."""
    import notifications.emails as emails
    from notifications.models import EmailLog

    real = emails.send_templated_email

    def fake(template, context, to, **kwargs):
        if to[0].startswith("bounce@"):
            return EmailLog.objects.create(
                template=template, to_emails=to, status=EmailLog.STATUS_FAILED, error="ValidationError: to[0]"
            )
        if to[0].startswith("crash@"):
            raise RuntimeError("шаблон сломан")
        return real(template, context, to, **kwargs)

    monkeypatch.setattr(emails, "send_templated_email", fake)
    return locmem


def _due_now(*rows):
    PortalNotice.objects.filter(pk__in=[row.pk for row in rows]).update(
        email_due_at=timezone.now() - timedelta(minutes=1)
    )


def test_a_failing_row_does_not_block_the_others_and_ends_failed(flaky_mail, client_company):
    bounce = Contact.objects.create(
        company=client_company, name="Bounce", email="bounce@client.example", invited_at=timezone.now()
    )
    crash = Contact.objects.create(
        company=client_company, name="Crash", email="crash@client.example", invited_at=timezone.now()
    )
    good = Contact.objects.create(
        company=client_company, name="Good", email="good@client.example", invited_at=timezone.now()
    )
    rows = _by_contact(_notify(client_company, dedup="flaky"))
    # сбойные строки — раньше исправной: прежде они навсегда занимали голову очереди
    PortalNotice.objects.filter(pk__in=[rows[bounce.pk].pk, rows[crash.pk].pk]).update(
        email_due_at=timezone.now() - timedelta(hours=1)
    )
    _due_now(rows[good.pk])

    first = notices.send_due_emails()
    assert first["sent"] >= 1 and first["retry"] == 2
    assert [message.to for message in flaky_mail] == [["good@client.example"]], "исправная ушла, несмотря на сбойные"

    for _ in range(notices.MAX_EMAIL_ATTEMPTS - 1):
        _due_now(rows[bounce.pk], rows[crash.pk])
        notices.send_due_emails()
    for contact in (bounce, crash):
        row = PortalNotice.objects.get(pk=rows[contact.pk].pk)
        assert row.email_state == NoticeEmailState.FAILED and row.email_attempts == notices.MAX_EMAIL_ATTEMPTS
        assert row.email_reason, "причина записана"
    assert PortalNotice.objects.get(pk=rows[crash.pk].pk).email_reason == "RuntimeError", "без текста исключения"
    _due_now(rows[bounce.pk], rows[crash.pk])
    assert notices.send_due_emails()["sent"] + notices.send_due_emails()["retry"] == 0, "конечное состояние не крутится"
    assert len(flaky_mail) == 1


def test_retry_waits_for_the_pause(flaky_mail, client_company):
    bounce = Contact.objects.create(
        company=client_company, name="Bounce", email="bounce@client.example", invited_at=timezone.now()
    )
    row = _by_contact(_notify(client_company, dedup="pause"))[bounce.pk]
    assert notices.deliver_email(row.pk) == "retry"
    row.refresh_from_db()
    assert row.email_due_at > timezone.now() + notices.EMAIL_RETRY_DELAYS[0] - timedelta(minutes=1)
    assert notices.deliver_email(row.pk) == "not_due"


def test_task_time_limit_is_not_a_row_failure(monkeypatch, client_company, no_tg_contact):
    """Время задачи вышло (`SoftTimeLimitExceeded`) — это не сбой строки: исключение наружу, попытка не засчитана."""
    from celery.exceptions import SoftTimeLimitExceeded

    row = next(r for r in _notify(client_company, dedup="limit") if r.contact_id == no_tg_contact.pk)
    _due_now(row)

    def out_of_time(_notice_id):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(notices, "deliver_email", out_of_time)
    with pytest.raises(SoftTimeLimitExceeded):
        notices.send_due_emails()
    row.refresh_from_db()
    assert row.email_state == NoticeEmailState.PENDING and row.email_attempts == 0 and row.email_reason == ""


# ── 7. Ответ менеджера в чате кабинета (CHAT-1 → NOTIFY-2) ─────────────────────────────────────────────────────────────


def _reply(company, message_id=7001, text="Счёт сегодня"):
    from portal.services import messages as chat

    return chat.apply_manager_reply(
        {
            "erp_company_id": company.pk,
            "message_id": message_id,
            "text": text,
            "manager_name": "Manager",
            "sent_at": timezone.now().isoformat(),
        }
    )


def _reply_row(message, contact):
    return PortalNotice.objects.get(kind="manager_replied", object_id=message.pk, contact=contact)


def test_manager_reply_is_a_bell_item_and_a_delayed_email(client_company, client_contact, no_tg_contact):
    message = _reply(client_company)
    _reply(client_company)  # повтор события `crm.cabinet.message_sent` — без второй строки
    assert PortalNotice.objects.filter(kind="manager_replied", contact=no_tg_contact).count() == 1
    row = _reply_row(message, no_tg_contact)
    assert (row.group, row.object_type, row.action, row.link) == ("messages", "chat", "replied", "/messages")
    assert row.channel == NoticeChannel.EMAIL_DELAYED and row.email_state == NoticeEmailState.PENDING
    # контакт сделки с Telegram, но не приглашён и не контакт документа — только колокольчик
    assert _reply_row(message, client_contact).channel == NoticeChannel.CABINET


def test_contact_in_the_chat_now_gets_no_email(client_company, no_tg_contact):
    """«Контакт сейчас в кабинете — только кабинет» (ADR-0023): смотрит ленту — письма нет вовсе."""
    from portal.models import PortalChatReader

    PortalChatReader.objects.create(company=client_company, contact=no_tg_contact, last_seen_at=timezone.now())
    row = _reply_row(_reply(client_company), no_tg_contact)
    assert row.channel == NoticeChannel.CABINET and row.email_reason == "present"


def test_a_series_of_replies_is_one_email(client_company, no_tg_contact):
    first = _reply_row(_reply(client_company, 7001), no_tg_contact)
    second = _reply_row(_reply(client_company, 7002), no_tg_contact)
    assert first.email_state == NoticeEmailState.PENDING
    assert second.channel == NoticeChannel.CABINET and second.email_reason == "batched"


def test_reading_the_chat_reads_the_notice_and_cancels_the_email(locmem, client_company, no_tg_contact):
    """Защита 3: прочтение в чате (`POST /messages/read`) гасит уведомление и отложенное письмо."""
    from portal.services import messages as chat

    message = _reply(client_company)
    chat.mark_read(client_company, no_tg_contact, message.pk)
    row = _reply_row(message, no_tg_contact)
    assert row.read_at is not None
    assert row.email_state == NoticeEmailState.CANCELLED and row.email_reason == "read_in_chat"
    _due_now(row)
    assert notices.send_due_emails()["sent"] == 0 and locmem == []


def test_delivery_rechecks_the_chat_read_mark(locmem, client_company, no_tg_contact):
    """Защита 4: отметка «прочитано» ленты, записанная мимо `mark_read` (гонка с задачей), гасит письмо при отправке."""
    from portal.models import PortalChatReader

    message = _reply(client_company)
    row = _reply_row(message, no_tg_contact)
    PortalChatReader.objects.create(company=client_company, contact=no_tg_contact, last_read_id=message.pk)
    _due_now(row)
    assert notices.deliver_email(row.pk) == "cancelled"
    row.refresh_from_db()
    assert row.email_reason == "read_in_chat" and locmem == []


def test_chat_presence_after_the_reply_cancels_the_email(locmem, client_company, no_tg_contact):
    """Защита 5: контакт открыл чат после ответа (опрос ленты, `last_seen_at`) — письма нет."""
    from portal.models import PortalChatReader

    row = _reply_row(_reply(client_company), no_tg_contact)
    PortalChatReader.objects.create(
        company=client_company, contact=no_tg_contact, last_seen_at=timezone.now() + timedelta(seconds=1)
    )
    _due_now(row)
    assert notices.deliver_email(row.pk) == "cancelled"
    row.refresh_from_db()
    assert row.email_reason == "present" and locmem == []


def test_unread_reply_goes_by_email_after_the_delay(locmem, client_company, no_tg_contact):
    row = _reply_row(_reply(client_company), no_tg_contact)
    _due_now(row)
    assert notices.send_due_emails()["sent"] == 1
    assert [message.to for message in locmem] == [["nodira@client.example"]]


# ── 8. Решение по карточке партнёра (PART-3 вызовет вместо прямого письма) ─────────────────────────────────────────────


def _partner_product(company):
    from catalog.models import Product, ProductStatus

    status, _ = ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})
    return Product.objects.create(name="Болт М12", status=status, source_supplier=company)


@pytest.mark.parametrize(
    ("decision", "kind"), [("published", "partner_card_published"), ("returned", "partner_card_returned")]
)
def test_partner_card_decision_is_a_bell_item_and_an_email(
    supplier_partner, enqueued, decision, kind, django_capture_on_commit_callbacks
):
    company, contact, client = supplier_partner
    Contact.objects.filter(pk=contact.pk).update(invited_at=timezone.now())
    product = _partner_product(company)
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            notice_sources.partner_card_decision(product, decision, reason="Нет артикула", issues=[{"field": "name"}])
            == 1
        )
    row = PortalNotice.objects.get(kind=kind, contact=contact)
    assert (row.group, row.object_type, row.object_id, row.link) == (
        "partner_products",
        "partner_product",
        product.pk,
        f"/my-products?card={product.pk}",
    )
    assert row.channel == NoticeChannel.EMAIL and enqueued == [row.pk]
    assert [item["id"] for item in client.get(f"{API}/notifications").json()["items"]] == [row.pk]


def test_partner_without_my_products_gets_no_card_notice(supplier_partner):
    from parties.models import CompanyRelationship

    company, contact, _client = supplier_partner
    CompanyRelationship.objects.filter(company=company).update(modules=["catalog_requests"])
    assert notice_sources.partner_card_decision(_partner_product(company), "returned", reason="x") == 0
    assert notice_sources.partner_card_decision(_partner_product(company), "unknown") == 0
