"""Tests for ERP SSO (Employee CRM ↔ ERP SSO, CONTRACTS §6, packages/contracts/sso-token.md, M3-CRM-06).

Тестирует:
1. Выпуск SSO-токена (POST /api/v1/auth/sso/token/)
2. Проверку и обмен токена на сессию (POST /api/v1/auth/sso/exchange/)
3. Защиту от повторного использования jti (replay attack, 10 минут)
4. Ротацию секретов (подпись вторым активным ключом)
5. Провижининг/обновление пользователя и запись в аудит ActivityLog
6. Отказ при деактивированном пользователе (403) и невалидной подписи/aud/exp (401)
"""

import time
import uuid

import jwt
import pytest
from django.core.cache import cache
from integration.models import CrmUserMapping
from rest_framework import status
from rest_framework.test import APIClient
from sales.models import ActivityLog

from accounts.models import CustomUser

pytestmark = pytest.mark.django_db

SSO_SECRET_PRIMARY = "test-platform-sso-secret-primary"
SSO_SECRET_SECONDARY = "test-platform-sso-secret-secondary"


@pytest.fixture(autouse=True)
def setup_sso_settings(settings):
    settings.PLATFORM_SSO_SECRET = [SSO_SECRET_PRIMARY, SSO_SECRET_SECONDARY]
    settings.CRM_FRONTEND_URL = "http://crm.localhost"
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def staff_user():
    user = CustomUser.objects.create(
        username="staff@example.com",
        email="staff@example.com",
        first_name="Алексей",
        is_staff=True,
        is_active=True,
    )
    CrmUserMapping.objects.create(crm_user_id=42, user=user)
    return user


def make_sso_jwt(
    secret: str = SSO_SECRET_PRIMARY,
    iss: str = "crm",
    aud: str = "erp",
    sub: str = "42",
    email: str = "staff@example.com",
    name: str = "Алексей Иванов",
    role: str = "manager",
    permissions: list | None = None,
    ttl_s: int = 60,
    jti: str | None = None,
    now: int | None = None,
) -> str:
    iat = now if now is not None else int(time.time())
    payload = {
        "iss": iss,
        "aud": aud,
        "sub": str(sub),
        "email": email,
        "name": name,
        "role": role,
        "permissions": permissions or ["quote.build", "deal.manage"],
        "iat": iat,
        "exp": iat + ttl_s,
        "jti": jti or str(uuid.uuid4()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ─── 1. Issue SSO Token ───────────────────────────────────────────────────────


def test_issue_sso_token_requires_authentication(client):
    resp = client.post("/api/v1/auth/sso/token/")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_issue_sso_token_success(client, staff_user):
    client.force_authenticate(user=staff_user)
    resp = client.post("/api/v1/auth/sso/token/")
    assert resp.status_code == status.HTTP_200_OK

    data = resp.json()
    assert "token" in data
    assert data["redirect_url"] == "http://crm.localhost/sso/exchange"

    payload = jwt.decode(
        data["token"],
        SSO_SECRET_PRIMARY,
        algorithms=["HS256"],
        audience="crm",
        issuer="erp",
    )
    assert payload["sub"] == "42"
    assert payload["email"] == "staff@example.com"
    assert payload["iss"] == "erp"
    assert payload["aud"] == "crm"
    assert payload["role"] == "manager"
    assert payload["exp"] > payload["iat"]


# ─── 2. Exchange SSO Token ─────────────────────────────────────────────────────


def test_exchange_missing_token(client):
    resp = client.post("/api/v1/auth/sso/exchange/", data={}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["detail"] == "TOKEN_REQUIRED"


def test_exchange_invalid_signature(client):
    token = make_sso_jwt(secret="wrong-secret-key")
    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["detail"] == "INVALID_SSO_TOKEN"


def test_exchange_wrong_aud(client):
    token = make_sso_jwt(aud="other")
    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["detail"] == "INVALID_SSO_TOKEN"


def test_exchange_wrong_iss(client):
    token = make_sso_jwt(iss="unknown")
    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["detail"] == "INVALID_SSO_TOKEN"


def test_exchange_expired_token(client):
    past = int(time.time()) - 100
    token = make_sso_jwt(now=past, ttl_s=60)
    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["detail"] == "INVALID_SSO_TOKEN"


def test_exchange_replay_protection_blocks_second_use(client):
    unique_jti = str(uuid.uuid4())
    token = make_sso_jwt(jti=unique_jti)

    # Первый обмен — успех
    resp1 = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp1.status_code == status.HTTP_200_OK

    # Второй обмен с тем же jti — отклоняется (401)
    resp2 = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp2.json()["detail"] == "TOKEN_ALREADY_USED"


def test_exchange_key_rotation_supports_secondary_secret(client):
    token = make_sso_jwt(secret=SSO_SECRET_SECONDARY)
    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp.status_code == status.HTTP_200_OK
    assert "access_token" in resp.json()


def test_exchange_success_issues_session_and_records_audit(client, staff_user):
    token = make_sso_jwt(
        sub="42",
        email="staff@example.com",
        name="Алексей Иванов Обновлённый",
        role="manager",
        permissions=["quote.build", "deal.manage", "catalog.manage"],
    )
    resp = client.post(
        "/api/v1/auth/sso/exchange/",
        data={"token": token},
        format="json",
        REMOTE_ADDR="192.168.1.100",
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert "access_token" in data
    assert "refresh_token" in data
    assert data["expires_in"] > 0
    assert "user" in data

    user_info = data["user"]
    assert user_info["erp_user_id"] == staff_user.pk
    assert user_info["crm_user_id"] == 42
    assert user_info["email"] == "staff@example.com"
    assert "platform_access" in user_info
    assert "crm" in user_info["platform_access"]
    assert "erp" in user_info["platform_access"]

    # Проверка обновления профиля
    staff_user.refresh_from_db()
    assert staff_user.first_name == "Алексей Иванов Обновлённый"

    # Проверка аудита ActivityLog
    log = ActivityLog.objects.filter(action="sso.exchange", user=staff_user).order_by("-id").first()
    assert log is not None
    assert log.event_code == "sso.exchange"
    assert log.event_params["iss"] == "crm"
    assert log.event_params["sub"] == "42"


def test_exchange_deactivated_user_returns_403(client):
    inactive_user = CustomUser.objects.create(
        username="inactive@example.com",
        email="inactive@example.com",
        is_active=False,
    )
    CrmUserMapping.objects.create(crm_user_id=999, user=inactive_user)

    token = make_sso_jwt(sub="999", email="inactive@example.com")
    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    # Должен отказать 403 FORBIDDEN
    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json()["detail"] == "USER_INACTIVE"
