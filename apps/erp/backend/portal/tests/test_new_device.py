"""ДВ-6: вход в кабинет с нового устройства — событие журнала безопасности и уведомление администраторам компании.

Устройство — метка в cookie `portal_device`; каждый `PortalAPIClient` — отдельный браузер со своими cookie.
"""

from __future__ import annotations

import re

import pytest
from django.core import mail
from portal.models import PortalKnownDevice, PortalNotice, PortalSecurityEvent, PortalSession
from portal.services.new_device import short_device
from portal.tests.conftest import LOCMEM_BACKEND, PortalAPIClient

MAGIC_LINK_URL = "/api/portal/v1/auth/magic-link"
CODE_URL = "/api/portal/v1/auth/code"
LOG = "/api/portal/v1/company/security-log"
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


@pytest.fixture(autouse=True)
def _locmem_mail(settings, inline_magic_link_task):
    settings.EMAIL_BACKEND = LOCMEM_BACKEND
    settings.CABINET_URL = "http://cabinet.localhost"


def sign_in(client: PortalAPIClient, email: str, **extra):
    client.post(MAGIC_LINK_URL, {"email": email}, format="json")
    code = re.search(r"(?:Код входа|Login code|Kirish kodi): (\d{6})", mail.outbox[-1].body).group(1)
    response = client.post(CODE_URL, {"email": email, "code": code}, format="json", **extra)
    assert response.status_code == 200, response.content
    return response


def new_device_events():
    return PortalSecurityEvent.objects.filter(event_type=PortalSecurityEvent.EventType.LOGIN_NEW_DEVICE)


def test_first_login_only_remembers_the_device(client_contact):
    office = PortalAPIClient()

    response = sign_in(office, client_contact.email)

    assert re.fullmatch(r"[0-9a-f]{64}", response.cookies["portal_device"].value)
    assert response.cookies["portal_device"]["httponly"]
    assert PortalKnownDevice.objects.filter(contact=client_contact).count() == 1
    assert not new_device_events().exists()


def test_same_device_again_is_quiet(client_contact):
    office = PortalAPIClient()
    sign_in(office, client_contact.email)
    again = sign_in(office, client_contact.email)

    assert "portal_device" not in again.cookies  # метка уже есть — не переставляем
    assert not new_device_events().exists()


def test_new_device_writes_event_and_notifies_admins(client_contact):
    sign_in(PortalAPIClient(), client_contact.email)

    sign_in(PortalAPIClient(), client_contact.email, HTTP_USER_AGENT=CHROME)

    event = new_device_events().get()
    assert event.actor_contact == client_contact and event.details == "Chrome · Windows"
    assert event.session is not None
    notice = PortalNotice.objects.get(kind="new_device_login", contact=client_contact)
    assert notice.params["name"] == client_contact.name and notice.params["device"] == "Chrome · Windows"


def test_admin_ends_the_new_device_session(client_contact):
    office = PortalAPIClient()
    sign_in(office, client_contact.email)
    stranger = PortalAPIClient()
    sign_in(stranger, client_contact.email)
    event = new_device_events().get()
    stranger_session = event.session_id

    row = next(item for item in office.get(LOG).json()["items"] if item["id"] == event.pk)
    assert row["event_type"] == "login_new_device" and row["can_end_session"] is True

    assert office.post(f"{LOG}/{event.pk}/end-session").status_code == 204
    assert not PortalSession.objects.filter(pk=stranger_session).exists()
    assert stranger.get("/api/portal/v1/me").status_code == 401
    again = office.post(f"{LOG}/{event.pk}/end-session")
    assert again.status_code == 409 and again.json()["detail"] == "SESSION_ALREADY_ENDED"
    row = next(item for item in office.get(LOG).json()["items"] if item["id"] == event.pk)
    assert row["can_end_session"] is False
    assert PortalSecurityEvent.objects.filter(event_type="revoke_sessions", target_contact=client_contact).exists()


def test_only_admins_end_sessions(client_contact, readonly_contact):
    sign_in(PortalAPIClient(), client_contact.email)
    sign_in(PortalAPIClient(), client_contact.email)
    event = new_device_events().get()
    colleague = PortalAPIClient()
    sign_in(colleague, readonly_contact.email)

    assert colleague.post(f"{LOG}/{event.pk}/end-session").status_code == 403


def test_short_device_names_browser_and_system():
    assert short_device(CHROME) == "Chrome · Windows"
    assert short_device("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605 Version/17.0 Safari/604.1") == (
        "Safari · iPhone"
    )
    assert short_device("") == ""
