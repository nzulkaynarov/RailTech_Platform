"""FIX-60a (контракт 0.3.0): код акцепта в Telegram — событием `quote.acceptance_code_requested`, а не вызовом Bot API.

* `POST /quotes/{id}/request-code` для контакта с Telegram и сопоставлением в CRM публикует событие на шину rt_bus (тело —
  по схеме `packages/contracts/events/erp/`, в одной транзакции с выпуском кода); иначе — письмо, как раньше. Прямого вызова
  Telegram и флага `PORTAL_ACCEPT_CODE_TELEGRAM` больше нет (Q-FIX22-1);
* `payload.code` не попадает в outbox шины (там маска `***`), в логи и в `EmailLog`: настоящее значение живёт только в кэше
  (`DjangoCacheStash`, 20 минут) до доставки. Сбой публикации откатывает выпуск кода, а не уводит на письмо;
* код привязан к контакту: другой контакт той же компании погасить его не может — `QUOTE_CODE_INVALID` (Q-FIX22-6);
* `quote.accepted|rejected` несут `erp_contact_id`/`crm_contact_id` того, кто решил (Q-FIX22-6), тело — по схеме.
"""

from __future__ import annotations

import json
import re

import pytest
from django.conf import settings as django_settings
from django.core import mail
from integration.models import CrmClientMapping, CrmContactMapping
from integration.services import events as bus_events
from integration.tests import bus_support
from parties.models import Contact
from portal.services import acceptance
from portal.tests.conftest import LOCMEM_CHANNELS, PortalAPIClient, issue_test_acceptance_code, make_portal_session
from sales.models.acceptance import QuoteAcceptanceCode

from crm.constants import QuoteStatusCode
from notifications.models import EmailLog

pytestmark = pytest.mark.django_db

API = "/api/portal/v1"
CRM_CLIENT_ID = 4242
CRM_CONTACT_ID = 57
CODE_EVENT = "quote.acceptance_code_requested"


@pytest.fixture(autouse=True)
def _locmem_mail(settings):
    settings.EMAIL_CHANNELS = LOCMEM_CHANNELS
    mail.outbox.clear()


@pytest.fixture
def mapped(client_company):
    return CrmClientMapping.objects.create(company=client_company, crm_client_id=CRM_CLIENT_ID)


@pytest.fixture
def contact_mapped(client_contact):
    return CrmContactMapping.objects.create(contact=client_contact, crm_contact_id=CRM_CONTACT_ID)


def post(client, path, body=None):
    return client.post(f"{API}{path}", body if body is not None else {}, format="json")


def code_events():
    return bus_support.published(CODE_EVENT)


def requested_code(event) -> str:
    """Настоящий код из тела доставки (в outbox он замаскирован, значение — в кэше издателя)."""
    return bus_support.real_data(event)["payload"]["code"]


@pytest.fixture
def sent_quote(contract_world):
    return contract_world["quotes"]["sent"]


# ── Telegram: событие вместо Bot API ─────────────────────────────────────────────────────────────────


def test_telegram_contact_matched_in_crm_gets_the_event_and_no_email(
    sent_quote, portal_client, mapped, contact_mapped, client_contact
):
    response = post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert response.status_code == 202
    assert response.json() == {"channel": "telegram", "sent_to": "@a***", "expires_in": 900}
    assert not mail.outbox and not EmailLog.objects.filter(template="quote_acceptance_code").exists()
    event = bus_support.only(CODE_EVENT)
    assert event["type"] == "uz.railtech.erp.quote.acceptance_code_requested.v1"
    body = bus_support.real_data(event)
    assert not bus_support.registry().validate_data(event["type"], body, tolerant=False)
    row = QuoteAcceptanceCode.objects.get(quote=sent_quote)
    assert row.contact_id == client_contact.pk
    assert body["erp_company_id"] == sent_quote.deal.company_id and body["crm_client_id"] == CRM_CLIENT_ID
    assert body["actor"] == {"type": "client", "name": client_contact.name}
    assert body["payload"]["erp_quote_id"] == sent_quote.pk and body["payload"]["version"] == sent_quote.version
    assert (
        body["payload"]["erp_contact_id"] == client_contact.pk and body["payload"]["crm_contact_id"] == CRM_CONTACT_ID
    )
    assert body["payload"]["expires_at"] == row.expires_at.isoformat()
    assert re.fullmatch(r"[0-9]{6}", body["payload"]["code"])


def test_the_code_from_the_event_accepts_the_quote(sent_quote, portal_client, mapped, contact_mapped):
    post(portal_client, f"/quotes/{sent_quote.pk}/request-code")
    code = requested_code(bus_support.only(CODE_EVENT))

    wrong = post(portal_client, f"/quotes/{sent_quote.pk}/accept", {"code": "000000" if code != "000000" else "111111"})
    accepted = post(portal_client, f"/quotes/{sent_quote.pk}/accept", {"code": code})

    assert wrong.status_code == 409 and wrong.json() == {"detail": "QUOTE_CODE_INVALID"}
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"


def test_telegram_contact_without_a_crm_contact_gets_the_email(sent_quote, portal_client, mapped):
    """Контакт с Telegram, но без сопоставления с контактом CRM: боту писать некому — письмо, события нет."""
    response = post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert response.json()["channel"] == "email"
    assert mail.outbox and not code_events()


def test_company_not_matched_in_crm_gets_the_email(sent_quote, portal_client, contact_mapped):
    """Контакт сопоставлен, а компания с клиентом CRM — нет: событие не выпускается (CRM его не примет) — письмо."""
    response = post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert response.json()["channel"] == "email" and mail.outbox
    assert not code_events()


def test_contact_without_telegram_gets_the_email_even_if_matched(
    sent_quote, portal_client, mapped, contact_mapped, client_contact
):
    Contact.objects.filter(pk=client_contact.pk).update(telegram_user_id=None, telegram_username="")

    response = post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert response.json()["channel"] == "email" and mail.outbox
    assert not code_events()


def test_a_publication_failure_rolls_the_code_back_instead_of_falling_back_to_the_email(
    sent_quote, portal_client, mapped, contact_mapped, monkeypatch
):
    """Сбой шины или кэша секрета не глотается: выпуск кода откатывается, письмо не уходит (клиент запросит код снова)."""

    def broken(*args, **kwargs):
        raise RuntimeError("redis is down")

    monkeypatch.setattr(bus_events, "publish_quote_acceptance_code_requested", broken)
    with pytest.raises(RuntimeError):
        post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert not mail.outbox and not QuoteAcceptanceCode.objects.filter(quote=sent_quote).exists()
    assert not code_events()


def test_telegram_only_contact_without_a_crm_contact_and_without_email_is_422(
    sent_quote, portal_client, mapped, client_contact
):
    """Нет сопоставления с CRM и нет почты: канала нет."""
    Contact.objects.filter(pk=client_contact.pk).update(email="")

    response = post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert response.status_code == 422 and response.json() == {"detail": "CONTACT_CHANNEL_REQUIRED"}
    assert not code_events() and not mail.outbox


def test_erp_never_calls_the_telegram_bot_api_and_the_flag_is_gone(
    sent_quote, portal_client, mapped, contact_mapped, monkeypatch
):
    """Q-FIX22-1: из ERP в Telegram никто не пишет; настройки `PORTAL_ACCEPT_CODE_TELEGRAM` и функций отправки нет."""
    import httpx

    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(django_settings, "TELEGRAM_BOT_TOKEN", "123456:FAKE-TOKEN-FOR-TESTS", raising=False)

    response = post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert response.json()["channel"] == "telegram" and calls == []
    assert not hasattr(django_settings, "PORTAL_ACCEPT_CODE_TELEGRAM")
    assert not hasattr(acceptance, "send_text_via_bot") and not hasattr(acceptance, "telegram_delivery_enabled")
    assert not hasattr(acceptance, "httpx")


# ── Код не попадает в журналы ────────────────────────────────────────────────────────────────────────


def test_the_code_is_masked_in_the_outbox_and_never_logged(sent_quote, portal_client, mapped, contact_mapped, caplog):
    with caplog.at_level("DEBUG"):
        response = post(portal_client, f"/quotes/{sent_quote.pk}/request-code")
    assert response.status_code == 202
    event = bus_support.only(CODE_EVENT)
    code = requested_code(event)

    assert event["data"]["payload"]["code"] == "***"
    assert event["data"]["payload"]["erp_contact_id"], "остальные поля тела в outbox на месте"
    assert code not in json.dumps(event, ensure_ascii=False), "код в конверте outbox"
    assert code not in caplog.text, "код акцепта попал в лог"
    assert not EmailLog.objects.filter(template="quote_acceptance_code").exists()
    # Журнал шины целиком: ни одна строка ни одной таблицы не содержит код.
    from rt_bus.django.models import Delivery, Inbox, Outbox, SubscriberState

    for model in (Outbox, Delivery, Inbox, SubscriberState):
        for row in model.objects.values():
            assert code not in json.dumps(row, default=str, ensure_ascii=False)
    # В базе — только хеш кода.
    assert QuoteAcceptanceCode.objects.get(quote=sent_quote).code_hash != code


# ── Код привязан к контакту (Q-FIX22-6) ──────────────────────────────────────────────────────────────


@pytest.fixture
def colleague(client_company):
    """Второй контакт с правом действовать в той же компании и его сессия."""
    contact = Contact.objects.create(
        company=client_company,
        name="Colleague Contact",
        email="colleague@example.uz",
        telegram_user_id=111222333,
        can_act=True,
        language="ru",
    )
    session = make_portal_session(contact, client_company, "telegram")
    client = PortalAPIClient()
    client.cookies[django_settings.PORTAL_SESSION_COOKIE_NAME] = session.raw_token
    client.credentials(HTTP_X_PORTAL_SESSION=session.raw_token)
    client.contact = contact
    return client


def test_a_colleague_cannot_use_the_code_issued_to_another_contact(
    sent_quote, portal_client, colleague, client_contact
):
    post(portal_client, f"/quotes/{sent_quote.pk}/request-code")
    code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)

    stolen = post(colleague, f"/quotes/{sent_quote.pk}/accept", {"code": code})

    assert stolen.status_code == 409 and stolen.json() == {"detail": "QUOTE_CODE_INVALID"}
    sent_quote.refresh_from_db()
    assert sent_quote.status.code == QuoteStatusCode.SENT
    row = QuoteAcceptanceCode.objects.get(quote=sent_quote)
    assert row.consumed_at is None and row.attempts == 0, "чужая попытка не гасит код и не тратит попытки владельца"
    assert row.contact_id == client_contact.pk
    # владелец кода по-прежнему может принять
    assert post(portal_client, f"/quotes/{sent_quote.pk}/accept", {"code": code}).status_code == 200


def test_the_code_issued_to_the_colleague_is_for_the_colleague_only(sent_quote, portal_client, colleague):
    post(colleague, f"/quotes/{sent_quote.pk}/request-code")
    code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
    assert QuoteAcceptanceCode.objects.get(quote=sent_quote).contact_id == colleague.contact.pk

    assert post(portal_client, f"/quotes/{sent_quote.pk}/accept", {"code": code}).json() == {
        "detail": "QUOTE_CODE_INVALID"
    }
    assert post(colleague, f"/quotes/{sent_quote.pk}/accept", {"code": code}).status_code == 200


def test_a_code_without_a_contact_is_not_accepted_in_the_cabinet(sent_quote, portal_client, client_contact):
    """Код публичной страницы КП (адрес сделки, контакта нет) в Cabinet не гасится — и наоборот."""
    code = issue_test_acceptance_code(sent_quote, client_contact.email)

    response = post(portal_client, f"/quotes/{sent_quote.pk}/accept", {"code": code})

    assert response.status_code == 409 and response.json() == {"detail": "QUOTE_CODE_INVALID"}
    assert QuoteAcceptanceCode.objects.get(quote=sent_quote).consumed_at is None


def test_the_public_page_does_not_consume_a_cabinet_code(sent_quote, client_contact):
    from crm.services.public_page import verify_code_and_accept

    code = issue_test_acceptance_code(sent_quote, client_contact.email, contact=client_contact)

    accepted, error = verify_code_and_accept(sent_quote, code)

    assert accepted is None and error == "INVALID_CODE"
    assert QuoteAcceptanceCode.objects.get(quote=sent_quote).consumed_at is None


# ── quote.accepted|rejected несут контакт (Q-FIX22-6) ────────────────────────────────────────────────


def outcome(event_type):
    return bus_support.only(event_type)


def test_accepted_event_carries_the_contact_ids(sent_quote, portal_client, mapped, contact_mapped, client_contact):
    post(portal_client, f"/quotes/{sent_quote.pk}/request-code")
    code = requested_code(bus_support.only(CODE_EVENT))

    assert post(portal_client, f"/quotes/{sent_quote.pk}/accept", {"code": code}).status_code == 200

    event = outcome("quote.accepted")
    bus_support.assert_matches_contract(event)
    body = event["data"]
    assert body["payload"]["erp_contact_id"] == client_contact.pk
    assert body["payload"]["crm_contact_id"] == CRM_CONTACT_ID
    assert body["actor"] == {"type": "client", "name": client_contact.name}


def test_rejected_event_carries_the_contact_ids(sent_quote, portal_client, mapped, contact_mapped, client_contact):
    assert post(portal_client, f"/quotes/{sent_quote.pk}/reject", {"reason": "Дорого"}).status_code == 200

    event = outcome("quote.rejected")
    bus_support.assert_matches_contract(event)
    body = event["data"]
    assert body["payload"]["erp_contact_id"] == client_contact.pk
    assert body["payload"]["crm_contact_id"] == CRM_CONTACT_ID


def test_contact_not_matched_in_crm_has_a_null_crm_contact_id(sent_quote, portal_client, mapped, client_contact):
    assert post(portal_client, f"/quotes/{sent_quote.pk}/reject", {"reason": "Дорого"}).status_code == 200

    event = outcome("quote.rejected")
    bus_support.assert_matches_contract(event)
    body = event["data"]
    assert body["payload"]["erp_contact_id"] == client_contact.pk and body["payload"]["crm_contact_id"] is None


def test_the_public_page_decision_has_no_contact_ids(sent_quote, mapped, client_contact):
    """Решение с публичной страницы КП (не из Cabinet) контакта не называет: в теле полей нет."""
    from crm.services.public_page import reject_from_public_page

    rejected, error = reject_from_public_page(sent_quote, "Дорого")

    assert error is None and rejected is not None
    event = outcome("quote.rejected")
    bus_support.assert_matches_contract(event)
    body = event["data"]
    assert "erp_contact_id" not in body["payload"] and "crm_contact_id" not in body["payload"]


def test_a_contact_without_a_channel_does_not_touch_the_active_code_of_a_colleague(
    sent_quote, portal_client, colleague, client_contact
):
    """Канал проверяется ДО выпуска: 422 не гасит код коллеги и не оставляет «сиротский» активный код."""
    post(colleague, f"/quotes/{sent_quote.pk}/request-code")
    colleague_row = QuoteAcceptanceCode.objects.get(quote=sent_quote)
    # Контакт только с Telegram: ни сопоставления в CRM, ни почты.
    Contact.objects.filter(pk=client_contact.pk).update(email="")

    response = post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert response.status_code == 422 and response.json() == {"detail": "CONTACT_CHANNEL_REQUIRED"}
    rows = list(QuoteAcceptanceCode.objects.filter(quote=sent_quote))
    assert [row.pk for row in rows] == [colleague_row.pk], "код коллеги остался единственным активным"
    assert rows[0].consumed_at is None and rows[0].contact_id == colleague.contact.pk


def test_a_failed_publication_without_an_email_leaves_no_orphan_code(
    sent_quote, portal_client, mapped, contact_mapped, client_contact, monkeypatch
):
    def broken(*args, **kwargs):
        raise RuntimeError("redis is down")

    monkeypatch.setattr(bus_events, "publish_quote_acceptance_code_requested", broken)
    Contact.objects.filter(pk=client_contact.pk).update(email="")

    with pytest.raises(RuntimeError):
        post(portal_client, f"/quotes/{sent_quote.pk}/request-code")

    assert not QuoteAcceptanceCode.objects.filter(quote=sent_quote).exists()
