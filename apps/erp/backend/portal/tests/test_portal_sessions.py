"""Тесты управления сессиями контакта (J2, этап 8): GET /auth/sessions и POST /auth/sessions/revoke-others."""

from __future__ import annotations

from datetime import timedelta
import pytest
from django.utils import timezone
from portal.models import PortalSession
from portal.services.tokens import hash_token
from portal.tests.conftest import make_portal_session
from portal.tests.contract_support import check_response, component

pytestmark = pytest.mark.django_db

SESSIONS_URL = "/api/portal/v1/auth/sessions"
REVOKE_OTHERS_URL = "/api/portal/v1/auth/sessions/revoke-others"


def test_list_sessions_unauthorized(anon_portal_client):
    res = anon_portal_client.get(SESSIONS_URL)
    assert res.status_code == 401
    assert res.json() == {"detail": "UNAUTHORIZED"}


def test_revoke_others_unauthorized(anon_portal_client):
    res = anon_portal_client.post(REVOKE_OTHERS_URL)
    assert res.status_code == 401
    assert res.json() == {"detail": "UNAUTHORIZED"}


def test_list_sessions_returns_only_active_sessions_with_is_current(
    portal_client, client_session, client_contact, client_company
):
    now = timezone.now()
    # Создаём ещё одну активную сессию (с другого устройства)
    other_active = PortalSession.objects.create(
        contact=client_contact,
        company=client_company,
        token_hash=hash_token("test-other-token-12345"),
        auth_method="magic_link",
        ip_address="198.51.100.1",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        created_at=now - timedelta(hours=2),
        last_used_at=now - timedelta(hours=1),
        expires_at=now + timedelta(days=1),
    )
    # Создаём истёкшую сессию (не должна попасть в выдачу)
    PortalSession.objects.create(
        contact=client_contact,
        company=client_company,
        token_hash=hash_token("test-expired-token-12345"),
        auth_method="magic_link",
        ip_address="203.0.113.5",
        user_agent="OldBrowser/1.0",
        created_at=now - timedelta(days=10),
        last_used_at=now - timedelta(days=8),
        expires_at=now - timedelta(days=1),
    )

    res = portal_client.get(SESSIONS_URL)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 2

    # Проверка схемы каждого элемента
    for item in data:
        check_response(item, component("PortalSessionItem"))

    # Ищем текущую сессию и сессию с другого устройства
    current_items = [s for s in data if s["id"] == client_session.pk]
    other_items = [s for s in data if s["id"] == other_active.pk]
    assert len(current_items) == 1
    assert current_items[0]["is_current"] is True
    assert len(other_items) == 1
    assert other_items[0]["is_current"] is False


def test_revoke_other_sessions(
    portal_client, client_session, client_contact, client_company
):
    now = timezone.now()
    # Создаём 2 другие активные сессии
    s1 = PortalSession.objects.create(
        contact=client_contact,
        company=client_company,
        token_hash=hash_token("token-s1-12345"),
        auth_method="magic_link",
        ip_address="198.51.100.10",
        user_agent="Device 1",
        expires_at=now + timedelta(days=1),
    )
    s2 = PortalSession.objects.create(
        contact=client_contact,
        company=client_company,
        token_hash=hash_token("token-s2-12345"),
        auth_method="magic_link",
        ip_address="198.51.100.20",
        user_agent="Device 2",
        expires_at=now + timedelta(days=1),
    )

    assert PortalSession.objects.filter(contact=client_contact).count() == 3

    res = portal_client.post(REVOKE_OTHERS_URL)
    assert res.status_code == 200
    assert res.json() == {"revoked_count": 2}

    # В базе осталась ровно одна сессия — текущая
    remaining = list(PortalSession.objects.filter(contact=client_contact))
    assert len(remaining) == 1
    assert remaining[0].pk == client_session.pk
