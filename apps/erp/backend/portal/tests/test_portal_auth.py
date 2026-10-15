"""Tests for Portal Authentication (Telegram initData, Magic Link, Logout, Me)."""

import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.utils import timezone
from portal.models import MagicLinkToken, PortalSession
from portal.tests.conftest import make_telegram_init_data
from rest_framework import status


@pytest.mark.django_db
class TestTelegramAuth:
    def test_telegram_auth_success(self, bot_token, client_contact, anon_portal_client):
        init_data = make_telegram_init_data(
            user_id=client_contact.telegram_user_id,
            username=client_contact.telegram_username,
            bot_token=bot_token,
        )

        response = anon_portal_client.post(
            "/api/portal/v1/auth/telegram",
            {"init_data": init_data},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["contact"]["id"] == client_contact.id
        assert data["contact"]["name"] == client_contact.name
        assert data["company"]["id"] == client_contact.company.id
        assert data["can_act"] is True

        # Проверка cookie
        cookie_name = settings.PORTAL_SESSION_COOKIE_NAME
        assert cookie_name in response.cookies
        session_token = response.cookies[cookie_name].value
        assert PortalSession.objects.filter(token=session_token, contact=client_contact).exists()

    def test_telegram_auth_invalid_hash(self, bot_token, client_contact, anon_portal_client):
        init_data = make_telegram_init_data(
            user_id=client_contact.telegram_user_id,
            bot_token=bot_token,
        )
        tampered = init_data.replace("hash=", "hash=broken1234567890")

        response = anon_portal_client.post(
            "/api/portal/v1/auth/telegram",
            {"init_data": tampered},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "INVALID_INIT_DATA"

    def test_telegram_auth_expired(self, bot_token, client_contact, anon_portal_client):
        # auth_date 10 минут назад (> 300с)
        old_auth_date = int(time.time()) - 600
        init_data = make_telegram_init_data(
            user_id=client_contact.telegram_user_id,
            bot_token=bot_token,
            auth_date=old_auth_date,
        )

        response = anon_portal_client.post(
            "/api/portal/v1/auth/telegram",
            {"init_data": init_data},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "INVALID_INIT_DATA"

    def test_telegram_auth_unknown_contact(self, bot_token, anon_portal_client):
        init_data = make_telegram_init_data(
            user_id=999888777,
            username="unknown_stranger",
            bot_token=bot_token,
        )

        response = anon_portal_client.post(
            "/api/portal/v1/auth/telegram",
            {"init_data": init_data},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "UNAUTHORIZED"


@pytest.mark.django_db
class TestMagicLinkAuth:
    @patch("django.core.mail.send_mail")
    def test_magic_link_flow_success(self, mock_send_mail, client_contact, anon_portal_client):
        # 1. Запрос ссылки
        req_resp = anon_portal_client.post(
            "/api/portal/v1/auth/magic-link",
            {"email": client_contact.email},
            format="json",
        )

        assert req_resp.status_code == status.HTTP_200_OK
        assert req_resp.data["sent"] is True
        assert req_resp.data["email"] == client_contact.email
        assert mock_send_mail.called

        token_obj = MagicLinkToken.objects.filter(contact=client_contact).first()
        assert token_obj is not None
        assert token_obj.is_valid() is True

        # 2. Обмен токена на сессию
        exchange_resp = anon_portal_client.post(
            f"/api/portal/v1/auth/magic/{token_obj.token}",
            format="json",
        )

        assert exchange_resp.status_code == status.HTTP_200_OK
        assert exchange_resp.data["contact"]["id"] == client_contact.id
        assert settings.PORTAL_SESSION_COOKIE_NAME in exchange_resp.cookies

        # Токен теперь погашен
        token_obj.refresh_from_db()
        assert token_obj.used_at is not None
        assert token_obj.is_valid() is False

    def test_magic_link_unknown_email(self, anon_portal_client):
        req_resp = anon_portal_client.post(
            "/api/portal/v1/auth/magic-link",
            {"email": "unknown.person@example.com"},
            format="json",
        )

        # Не раскрываем отсутствие email, отдаем 200 {"sent": true}
        assert req_resp.status_code == status.HTTP_200_OK
        assert req_resp.data["sent"] is True
        assert not MagicLinkToken.objects.filter(contact__email="unknown.person@example.com").exists()

    def test_magic_link_expired(self, client_contact, anon_portal_client):
        token_obj = MagicLinkToken.objects.create(
            token="expired_token_123",
            contact=client_contact,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        resp = anon_portal_client.post(
            f"/api/portal/v1/auth/magic/{token_obj.token}",
            format="json",
        )

        assert resp.status_code == status.HTTP_410_GONE
        assert resp.data["detail"] == "MAGIC_LINK_EXPIRED"

    def test_magic_link_already_used(self, client_contact, anon_portal_client):
        token_obj = MagicLinkToken.objects.create(
            token="used_token_123",
            contact=client_contact,
            expires_at=timezone.now() + timedelta(minutes=15),
            used_at=timezone.now() - timedelta(minutes=2),
        )

        resp = anon_portal_client.post(
            f"/api/portal/v1/auth/magic/{token_obj.token}",
            format="json",
        )

        assert resp.status_code == status.HTTP_410_GONE
        assert resp.data["detail"] == "MAGIC_LINK_EXPIRED"


@pytest.mark.django_db
class TestLogoutAndMe:
    def test_me_authenticated(self, portal_client, client_contact, client_company):
        response = portal_client.get("/api/portal/v1/me")
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert data["contact"]["id"] == client_contact.id
        assert data["contact"]["name"] == client_contact.name
        assert data["company"]["id"] == client_company.id
        assert data["can_act"] is True

    def test_me_unauthenticated(self, anon_portal_client):
        response = anon_portal_client.get("/api/portal/v1/me")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["detail"] == "UNAUTHORIZED"

    def test_logout(self, portal_client, client_session):
        assert PortalSession.objects.filter(token=client_session.token).exists()

        response = portal_client.post("/api/portal/v1/auth/logout")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Сессия удалена
        assert not PortalSession.objects.filter(token=client_session.token).exists()

        # Повторный запрос /me теперь 401
        me_resp = portal_client.get("/api/portal/v1/me")
        assert me_resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert me_resp.data["detail"] == "UNAUTHORIZED"
