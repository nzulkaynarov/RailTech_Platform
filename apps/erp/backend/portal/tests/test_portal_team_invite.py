"""`POST /team/invite` (FIX-23, P-17): приглашение без ложного «отправлено».

Доставляется только письмо. Telegram-бот принадлежит CRM, поэтому канал `telegram` отвечает 422 `INVALID_CHANNEL` и не
оставляет следов: ни контакта, ни письма, ни события `invite.sent`.
"""

from __future__ import annotations

import pytest
from django.core import mail
from integration.models import CrmClientMapping, IntegrationWebhookEvent
from parties.models import Contact
from portal.models import MagicLinkToken
from portal.tests.conftest import LOCMEM_CHANNELS
from portal.tests.contract_support import check_response, component

from notifications.models import EmailLog

pytestmark = pytest.mark.django_db

URL = "/api/portal/v1/team/invite"


@pytest.fixture(autouse=True)
def locmem(settings):
    settings.EMAIL_CHANNELS = LOCMEM_CHANNELS
    mail.outbox = []


def body(**overrides):
    data = {"name": "Dilshod Teammate", "email": "dilshod@example.uz", "language": "ru", "channels": ["email"]}
    data.update(overrides)
    return data


def invited(company, email="dilshod@example.uz"):
    return Contact.objects.filter(company=company, email=email)


def nothing_happened(company, email="dilshod@example.uz"):
    assert not invited(company, email).exists(), "контакт не должен появиться"
    assert mail.outbox == [], "письмо не должно уйти"
    assert not MagicLinkToken.objects.filter(purpose="invite").exists()
    assert not IntegrationWebhookEvent.objects.filter(event_type="invite.sent").exists()


# ── Канал telegram: честный отказ ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("channels", [["telegram"], ["email", "telegram"], ["telegram", "email"]])
def test_telegram_channel_is_refused_not_pretended(portal_client, client_company, channels):
    response = portal_client.post(URL, body(channels=channels, phone="+998901112233"), format="json")
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_CHANNEL"}
    nothing_happened(client_company)


def test_telegram_refusal_leaves_no_invite_event(portal_client, client_company):
    CrmClientMapping.objects.create(company=client_company, crm_client_id=77)
    portal_client.post(URL, body(channels=["telegram"]), format="json")
    assert not IntegrationWebhookEvent.objects.filter(event_type="invite.sent").exists()


# ── Email: настоящая доставка ────────────────────────────────────────────────────────────────────


def test_email_invitation_is_delivered(portal_client, client_company):
    CrmClientMapping.objects.create(company=client_company, crm_client_id=77)
    response = portal_client.post(URL, body(phone="+998901112233", can_act=True), format="json")
    assert response.status_code == 201, response.content
    data = response.json()
    assert not check_response(data, component("TeamMember"))
    assert data["email"] == "dilshod@example.uz" and data["can_act"] is True
    assert data["preferred_channel"] == "email" and data["invited_at"] is not None

    contact = invited(client_company).get()
    assert contact.invited_at is not None and not contact.is_primary
    assert [m.to for m in mail.outbox] == [["dilshod@example.uz"]]
    assert "/auth/magic#token=" in mail.outbox[0].body
    assert EmailLog.objects.filter(to_emails__contains="dilshod@example.uz", status=EmailLog.STATUS_SENT).count() == 1
    assert MagicLinkToken.objects.filter(contact=contact, purpose="invite").count() == 1

    event = IntegrationWebhookEvent.objects.get(event_type="invite.sent")
    assert event.payload["payload"]["channels"] == ["email"], "в событии — только то, что реально ушло"


def test_response_never_carries_the_login_link(portal_client):
    response = portal_client.post(URL, body(), format="json")
    assert response.status_code == 201
    assert "token" not in response.content.decode() and "magic" not in response.content.decode()


def test_email_is_normalized(portal_client, client_company):
    response = portal_client.post(URL, body(email="  Dilshod@Example.UZ "), format="json")
    assert response.status_code == 201
    assert invited(client_company).get().email == "dilshod@example.uz"


# ── Валидация ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"channels": []}, "VALIDATION_ERROR"),
        ({"channels": "email"}, "VALIDATION_ERROR"),
        ({"channels": ["sms"]}, "VALIDATION_ERROR"),
        ({"name": ""}, "VALIDATION_ERROR"),
        ({"name": "x" * 201}, "VALIDATION_ERROR"),
        ({"email": "not-an-email"}, "VALIDATION_ERROR"),
        ({"language": "fr"}, "VALIDATION_ERROR"),
        ({"email": ""}, "CONTACT_EMAIL_REQUIRED"),
    ],
)
def test_invalid_invitation_is_422_and_changes_nothing(portal_client, client_company, overrides, code):
    response = portal_client.post(URL, body(**overrides), format="json")
    assert response.status_code == 422 and response.json() == {"detail": code}
    nothing_happened(client_company)


def test_missing_channels_is_422(portal_client, client_company):
    data = body()
    del data["channels"]
    response = portal_client.post(URL, data, format="json")
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}
    nothing_happened(client_company)


def test_duplicate_email_in_company_is_refused(portal_client, client_company, client_contact):
    response = portal_client.post(URL, body(email=client_contact.email.upper()), format="json")
    assert response.status_code == 422 and response.json() == {"detail": "TEAM_MEMBER_EXISTS"}
    assert mail.outbox == []


def test_duplicate_phone_in_company_is_refused(portal_client, client_contact):
    response = portal_client.post(URL, body(phone=client_contact.phone), format="json")
    assert response.status_code == 422 and response.json() == {"detail": "TEAM_MEMBER_EXISTS"}


# ── Сбой доставки: не «отправлено» ────────────────────────────────────────────────────────────────


def test_failed_delivery_is_an_error_and_leaves_no_member(portal_client, client_company, settings):
    settings.EMAIL_CHANNELS = {
        name: {**cfg, "backend": "django.core.mail.backends.smtp.EmailBackend", "host": "127.0.0.1", "port": 1}
        for name, cfg in LOCMEM_CHANNELS.items()
    }
    response = portal_client.post(URL, body(), format="json")
    assert response.status_code == 503
    assert response.json() == {"detail": "DELIVERY_FAILED"}
    assert not invited(client_company).exists(), "коллеги в команде нет: приглашение не дошло"
    assert EmailLog.objects.filter(status=EmailLog.STATUS_FAILED).count() == 1, "сбой виден в журнале писем"
    assert not IntegrationWebhookEvent.objects.filter(event_type="invite.sent").exists()


def test_retry_after_failed_delivery_is_possible(portal_client, client_company, settings):
    good = settings.EMAIL_CHANNELS
    settings.EMAIL_CHANNELS = {
        name: {**cfg, "backend": "django.core.mail.backends.smtp.EmailBackend", "host": "127.0.0.1", "port": 1}
        for name, cfg in good.items()
    }
    assert portal_client.post(URL, body(), format="json").status_code == 503
    settings.EMAIL_CHANNELS = good
    assert portal_client.post(URL, body(), format="json").status_code == 201


# ── Права и изоляция ─────────────────────────────────────────────────────────────────────────────


def test_read_only_contact_cannot_invite(readonly_portal_client, client_company):
    response = readonly_portal_client.post(URL, body(), format="json")
    assert response.status_code == 403 and response.json() == {"detail": "FORBIDDEN"}
    nothing_happened(client_company)


def test_invitation_without_session_is_401(anon_portal_client):
    assert anon_portal_client.post(URL, body(), format="json").status_code == 401


def test_invited_colleague_joins_the_inviters_company_only(portal_client, client_company, other_company):
    portal_client.post(URL, body(), format="json")
    contact = Contact.objects.get(email="dilshod@example.uz")
    assert contact.company_id == client_company.pk and contact.company_id != other_company.pk


def test_same_email_in_another_company_is_not_a_duplicate(other_portal_client, client_contact, other_company):
    """Дубликат считается внутри своей компании: чужая команда адреса не занимает."""
    response = other_portal_client.post(URL, body(email=client_contact.email), format="json")
    assert response.status_code == 201
    assert Contact.objects.filter(company=other_company, email=client_contact.email).exists()


def test_team_list_shows_only_own_company(portal_client, other_contact):
    portal_client.post(URL, body(), format="json")
    emails = {m["email"] for m in portal_client.get("/api/portal/v1/team").json()}
    assert "dilshod@example.uz" in emails and other_contact.email not in emails


# ── Служба приглашения для сотрудников ERP: те же правила ──────────────────────────────────────────


def test_staff_invite_service_refuses_telegram_only(client_contact):
    from portal.services.invitation import invite_contact_to_portal

    result, error = invite_contact_to_portal(client_contact, channel="telegram")
    assert result is None and error == "INVALID_CHANNEL"
    assert mail.outbox == [] and not IntegrationWebhookEvent.objects.filter(event_type="invite.sent").exists()


def test_staff_invite_service_both_sends_email_and_names_only_what_went_out(client_contact):
    from portal.services.invitation import invite_contact_to_portal

    result, error = invite_contact_to_portal(client_contact, channel="both")
    assert error is None
    assert result["channel"] == "email" and result["email_sent"] is True  # telegram не отправлялся — и не назван
    assert len(mail.outbox) == 1
    event = IntegrationWebhookEvent.objects.filter(event_type="invite.sent")
    assert not event.exists() or event.get().payload["payload"]["channels"] == ["email"]
