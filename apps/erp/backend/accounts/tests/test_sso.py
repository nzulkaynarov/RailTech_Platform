"""Tests for ERP SSO (Employee CRM ↔ ERP SSO, CONTRACTS §6, docs/architecture/sso-token.md, M3-CRM-06).

Тестирует:
1. Выпуск SSO-токена (POST /api/v1/auth/sso/token/)
2. Проверку и обмен токена на сессию (POST /api/v1/auth/sso/exchange/)
3. Защиту от повторного использования jti (replay attack, 10 минут)
4. Ротацию секретов (подпись вторым активным ключом)
5. Обновление email/name и запись в аудит ActivityLog; обмен не создаёт пользователей и не меняет права (FIX-10)
6. Отказ при деактивированном/непровиженном пользователе (403) и невалидной подписи/aud/exp (401)
7. Ограничение exp − iat ≤ 60 (с допуском 5 с)
"""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.core.cache import cache
from integration.models import CrmUserMapping
from rest_framework import status
from rest_framework.test import APIClient
from sales.models import ActivityLog

from accounts.models import CompanyMember, CustomUser

pytestmark = pytest.mark.django_db

SSO_SECRET_PRIMARY = "test-platform-sso-secret-primary"
SSO_SECRET_SECONDARY = "test-platform-sso-secret-secondary"


@pytest.fixture(autouse=True)
def setup_sso_settings(settings):
    settings.PLATFORM_SSO_SECRET = [SSO_SECRET_PRIMARY, SSO_SECRET_SECONDARY]
    settings.PLATFORM_SSO_ENABLED = True
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


def test_exchange_replay_protection_blocks_second_use(client, staff_user):
    unique_jti = str(uuid.uuid4())
    token = make_sso_jwt(jti=unique_jti)

    # Первый обмен — успех
    resp1 = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp1.status_code == status.HTTP_200_OK

    # Второй обмен с тем же jti — отклоняется (401)
    resp2 = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp2.json()["detail"] == "TOKEN_ALREADY_USED"


def test_exchange_key_rotation_supports_secondary_secret(client, staff_user):
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
    # S-14 (FIX-58): refresh — только HttpOnly-cookie, как при обычном входе; в теле обмена его нет.
    assert "refresh_token" not in data and "refresh" not in data
    assert settings.REFRESH_COOKIE_NAME in resp.cookies
    assert resp.cookies[settings.REFRESH_COOKIE_NAME]["httponly"]
    assert resp.cookies[settings.REFRESH_COOKIE_NAME].value
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
    # N-03 (FIX-64): полное имя из токена делится на имя и фамилию, а не целиком в first_name.
    assert (staff_user.first_name, staff_user.last_name) == ("Алексей", "Иванов Обновлённый")

    # Проверка аудита ActivityLog
    log = ActivityLog.objects.filter(action="sso.exchange", user=staff_user).order_by("-id").first()
    assert log is not None
    assert log.event_code == "sso.exchange"
    assert log.event_params["iss"] == "crm"
    assert log.event_params["sub"] == "42"


def _exchange_audit_ip(client, staff_user, **meta):
    resp = client.post(
        "/api/v1/auth/sso/exchange/",
        data={"token": make_sso_jwt(sub="42", email="staff@example.com")},
        format="json",
        **meta,
    )
    assert resp.status_code == status.HTTP_200_OK, resp.content
    return ActivityLog.objects.filter(action="sso.exchange", user=staff_user).order_by("-id").first().event_params["ip"]


def test_exchange_audit_ignores_forged_forwarded_for_without_trusted_proxy(client, staff_user, settings):
    """FIX-54 (S-15): без доверенного прокси (NUM_PROXIES=0) подделанный X-Forwarded-For в аудит не попадает."""
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}
    ip = _exchange_audit_ip(client, staff_user, REMOTE_ADDR="192.168.1.100", HTTP_X_FORWARDED_FOR="6.6.6.6, 7.7.7.7")
    assert ip == "192.168.1.100"


def test_exchange_audit_takes_the_address_added_by_the_trusted_proxy(client, staff_user, settings):
    """За одним доверенным прокси (Caddy) адрес клиента — последний в цепочке, а не первый, который шлёт сам клиент."""
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    ip = _exchange_audit_ip(client, staff_user, REMOTE_ADDR="172.18.0.2", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.7")
    assert ip == "203.0.113.7"


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


def test_sso_is_disabled_by_default_and_refused(client, staff_user, settings):
    """FIX-03: до волны 1 переход выключен (PLATFORM_SSO_ENABLED=false) — обе стороны отказывают,
    /me не показывает кнопку."""
    settings.PLATFORM_SSO_ENABLED = False
    client.force_authenticate(user=staff_user)

    issue = client.post("/api/v1/auth/sso/token/")
    exchange = client.post("/api/v1/auth/sso/exchange/", {"token": "anything"}, format="json")
    me = client.get("/api/v1/accounts/users/me/")

    assert issue.status_code == 403 and issue.data["detail"] == "SSO_DISABLED"
    assert exchange.status_code == 403 and exchange.data["detail"] == "SSO_DISABLED"
    assert me.status_code == 200 and me.data["capabilities"]["sso_enabled"] is False


# ─── 3. FIX-10: sub только из сопоставления, обмен без провижининга, exp − iat ≤ 60 ───


def test_issue_sso_token_without_mapping_is_refused(client):
    """S-2: запасного `sub = user.pk` нет — без CrmUserMapping токен не выдаётся."""
    unmapped = CustomUser.objects.create(username="u@example.com", email="u@example.com", is_active=True)
    client.force_authenticate(user=unmapped)

    resp = client.post("/api/v1/auth/sso/token/")

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"detail": "USER_NOT_PROVISIONED"}


def test_exchange_unknown_sub_is_forbidden_and_creates_no_user(client):
    """S-3: неизвестный sub → 403, пользователь ERP не создаётся и сопоставление не заводится."""
    users_before = CustomUser.objects.count()
    token = make_sso_jwt(sub="777", email="newcomer@example.com", role="admin", permissions=["quote.build"])

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"detail": "USER_NOT_PROVISIONED"}
    assert CustomUser.objects.count() == users_before
    assert not CrmUserMapping.objects.filter(crm_user_id=777).exists()
    assert "access_token" not in resp.json()


def test_exchange_email_match_without_sub_is_forbidden_and_user_untouched(client):
    """S-3: e-mail совпал с пользователем ERP, а sub — нет: не привязываем и не трогаем права."""
    victim = CustomUser.objects.create(
        username="victim@example.com", email="victim@example.com", is_active=True, is_superuser=False, is_staff=False
    )
    token = make_sso_jwt(sub="888", email="victim@example.com", role="admin")

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_403_FORBIDDEN
    assert resp.json() == {"detail": "USER_NOT_PROVISIONED"}
    victim.refresh_from_db()
    assert victim.is_superuser is False and victim.is_staff is False
    assert not CrmUserMapping.objects.filter(user=victim).exists()
    assert not CompanyMember.objects.filter(user=victim).exists()


def test_exchange_does_not_change_superuser_or_permissions(client, staff_user):
    """S-3: role/permissions из токена при обмене не применяются (только провижинингом)."""
    token = make_sso_jwt(sub="42", role="admin", permissions=["quote.build", "finance.manage"])

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_200_OK
    staff_user.refresh_from_db()
    assert staff_user.is_superuser is False
    assert staff_user.is_staff is True
    assert not CompanyMember.objects.filter(user=staff_user).exists()
    assert resp.json()["user"]["permissions"] == []


def test_exchange_demotes_nobody_and_keeps_superuser(client):
    admin = CustomUser.objects.create(
        username="boss@example.com", email="boss@example.com", is_active=True, is_superuser=True, is_staff=True
    )
    CrmUserMapping.objects.create(crm_user_id=50, user=admin)
    token = make_sso_jwt(sub="50", email="boss@example.com", role="manager", permissions=[])

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_200_OK
    admin.refresh_from_db()
    assert admin.is_superuser is True and admin.is_staff is True


def test_exchange_updates_email_and_name_only(client, staff_user):
    token = make_sso_jwt(sub="42", email="Renamed@Example.com", name="Новое Имя")

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_200_OK
    staff_user.refresh_from_db()
    assert staff_user.email == "renamed@example.com"
    assert (staff_user.first_name, staff_user.last_name) == ("Новое", "Имя")


def test_exchange_email_taken_by_other_user_is_not_overwritten(client, staff_user):
    CustomUser.objects.create(username="other@example.com", email="other@example.com", is_active=True)
    token = make_sso_jwt(sub="42", email="other@example.com")

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_200_OK
    staff_user.refresh_from_db()
    assert staff_user.email == "staff@example.com"


def test_exchange_lifetime_over_60s_is_rejected_even_with_valid_signature(client, staff_user):
    """S-7: exp − iat = 120 с при верной подписи и неистёкшем exp → 401."""
    token = make_sso_jwt(ttl_s=120)

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json() == {"detail": "INVALID_SSO_TOKEN"}


def test_exchange_lifetime_within_leeway_is_accepted(client, staff_user):
    token = make_sso_jwt(ttl_s=65)

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_200_OK


def test_exchange_lifetime_just_over_leeway_is_rejected(client, staff_user):
    token = make_sso_jwt(ttl_s=66)

    resp = client.post("/api/v1/auth/sso/exchange/", data={"token": token}, format="json")

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
