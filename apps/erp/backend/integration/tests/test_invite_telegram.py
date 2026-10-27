"""Приглашение в Cabinet через Telegram (D1-9, Q-FIX23-1): `invite.requested` для бота CRM и повторное приглашение из CRM.

ERP в Telegram не пишет: канал `telegram` — событие шины, доставляет бот CRM. Событие уходит только контакту с привязанным
`telegram_user_id` и сопоставлением с контактом CRM; иначе — код причины (`CONTACT_TELEGRAM_REQUIRED`), а не молчаливый успех.
"""

from __future__ import annotations

import uuid

import pytest
from django.core import mail
from integration.tests import bus_support
from integration.tests.test_handoff import handoff, payload
from parties.models import CompanyType, Contact
from portal.services.invitation import invite_contact_to_portal
from rest_framework.test import APIClient

SERVICE_TOKEN = "test-crm-to-erp-token"


@pytest.fixture(autouse=True)
def integration_env(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    settings.CABINET_URL = "http://cabinet.localhost"
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})


@pytest.fixture
def api():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return client


def invite(api, crm_client_id, body):
    return api.post(
        f"/api/integration/v1/clients/{crm_client_id}/invite",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )


def handed_off(api, **kwargs):
    """Клиент передан без приглашения в канал telegram (письмо ушло): повторное приглашение — отдельный шаг."""
    resp = handoff(api, payload(channels=("email",), **kwargs))
    assert resp.status_code == 201
    mail.outbox.clear()
    bus_support.reset()
    return resp


@pytest.mark.django_db
def test_telegram_invite_publishes_event_for_the_crm_bot_and_sends_no_mail(api):
    handed_off(api)

    resp = invite(api, 1001, {"channel": "telegram"})

    assert resp.status_code == 200
    assert resp.json() == {"sent_via": ["telegram"], "cabinet_url": "http://cabinet.localhost", "error": None}
    event = bus_support.only("invite.requested")
    bus_support.assert_matches_contract(event)
    assert event["data"]["crm_client_id"] == 1001
    assert event["data"]["payload"]["crm_contact_id"] == 10011
    assert "token" not in str(event).lower(), "в событии нет ссылок входа и токенов"
    assert mail.outbox == []
    assert Contact.objects.get().invited_at is not None


@pytest.mark.django_db
def test_both_channels_send_mail_and_event(api):
    handed_off(api)

    resp = invite(api, 1001, {"channel": "both"})

    assert resp.json()["sent_via"] == ["email", "telegram"]
    assert len(mail.outbox) == 1
    assert len(bus_support.published("invite.requested")) == 1
    assert len(bus_support.published("invite.sent")) == 1


@pytest.mark.django_db
def test_contact_without_telegram_account_gets_a_reason_not_a_silent_success(api):
    body = payload(channels=("email",))
    body["contacts"][0]["telegram_user_id"] = None
    assert handoff(api, body).status_code == 201
    mail.outbox.clear()
    bus_support.reset()

    resp = invite(api, 1001, {"channel": "telegram"})

    assert resp.status_code == 200
    assert resp.json()["sent_via"] == []
    assert resp.json()["error"] == "CONTACT_TELEGRAM_REQUIRED"
    assert bus_support.published("invite.requested") == []


@pytest.mark.django_db
def test_both_without_email_still_goes_to_telegram_with_the_email_reason_hidden(api):
    handed_off(api, email="")

    resp = invite(api, 1001, {"channel": "both"})

    assert resp.json()["sent_via"] == ["telegram"]
    assert resp.json()["error"] is None, "ушло хотя бы одним каналом — ошибки нет"
    assert mail.outbox == []


@pytest.mark.django_db
def test_both_channels_unavailable_reports_channel_required(api):
    body = payload(channels=("email",), email="")
    body["contacts"][0]["telegram_user_id"] = None
    assert handoff(api, body).status_code == 201

    resp = invite(api, 1001, {"channel": "both"})

    assert resp.json()["sent_via"] == []
    assert resp.json()["error"] == "CONTACT_CHANNEL_REQUIRED"


@pytest.mark.django_db
def test_unknown_client_and_foreign_contact_are_404(api):
    handed_off(api)
    handoff(api, payload(crm_client_id=2002, inn="987654321", email="other@client.uz"))

    assert invite(api, 999999, {"channel": "email"}).status_code == 404
    # контакт другого клиента CRM по этому пути не находится
    assert invite(api, 1001, {"channel": "email", "crm_contact_id": 20021}).status_code == 404
    assert invite(api, 1001, {"channel": "sms"}).status_code == 422


@pytest.mark.django_db
def test_requires_service_token():
    resp = APIClient().post(
        "/api/integration/v1/clients/1001/invite",
        {"channel": "email"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_staff_endpoint_with_telegram_contact_reports_telegram_not_email(api):
    handed_off(api)
    contact = Contact.objects.get()
    result, error = invite_contact_to_portal(contact, actor=None, channel="telegram")

    assert error is None
    assert result["channel"] == "telegram"
    assert result["email_sent"] is False
