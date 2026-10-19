"""FIX-11 — доступом к ERP управляет CRM: провижининг, отзыв сессий и access-токенов (S-5, S-6, S-11).

Пути, которые проверяет файл (ADR-0003, packages/contracts/sso-token.md «Отзыв»):

* провижининг принимает только коды из каталога прав ERP (`accounts.constants.Permission`);
* `DELETE /api/integration/v1/users/{crm_user_id}/sessions` гасит refresh-токены, уже выданные
  access-токены (версия токенов пользователя растёт — старый access отвечает 401) и вход
  (`is_active=false`); пишет `sso.revoke` в аудит; идемпотентен;
* повторный провижининг включает пользователя, но прежний access остаётся мёртвым;
* `CookieTokenRefreshView` не продлевает refresh-токен того, кто больше не сотрудник;
* переключатель «В CRM» в шапке ERP — только у пользователя с `CrmUserMapping` (`capabilities.crm_access`).
"""

import time
import uuid

import jwt
import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from integration.models import CrmUserMapping
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from sales.models import ActivityLog

from accounts.constants import ALL_PERMISSIONS, Permission
from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-crm-to-erp-token"
SSO_SECRET = "test-sso-secret-fix11"
ME_URL = "/api/v1/accounts/me/"
USERS_ME_URL = "/api/v1/accounts/users/me/"  # профиль с `capabilities` (MeSerializer)
REFRESH_URL = "/api/v1/auth/token/refresh/"
HASLO = "Str0ng-Pass-FIX11"


@pytest.fixture(autouse=True)
def _env(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    settings.PLATFORM_SSO_SECRET = [SSO_SECRET]
    settings.PLATFORM_SSO_ENABLED = True
    cache.clear()


@pytest.fixture
def own_company(settings):
    supplier = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier"})[0]
    company = Company.objects.create(name="Своя компания", inn="500000001")
    company.types.add(supplier)
    settings.OWN_COMPANY_ID = company.pk
    return company


@pytest.fixture
def service():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return client


def provision(service, crm_user_id=7001, email="staff@example.com", role="backoffice", permissions=None, **extra):
    payload = {
        "crm_user_id": crm_user_id,
        "email": email,
        "name": "Сотрудник",
        "role": role,
        "permissions": ["deal.manage"] if permissions is None else permissions,
        **extra,
    }
    return service.post(
        "/api/integration/v1/users/provision", payload, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )


def revoke(service, crm_user_id=7001):
    return service.delete(f"/api/integration/v1/users/{crm_user_id}/sessions")


def sso_token(sub="7001"):
    now = int(time.time())
    payload = {
        "iss": "crm",
        "aud": "erp",
        "sub": sub,
        "email": "staff@example.com",
        "name": "Сотрудник",
        "role": "manager",
        "permissions": [],
        "iat": now,
        "exp": now + 60,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, SSO_SECRET, algorithm="HS256")


def sso_login(sub="7001"):
    """Вход так, как его делает сотрудник: SSO-обмен → access и refresh."""
    client = APIClient()
    response = client.post("/api/v1/auth/sso/exchange/", {"token": sso_token(sub)}, format="json")
    assert response.status_code == 200, response.content
    return response.json()["access_token"], response.json()["refresh_token"]


def bearer(access):
    client = APIClient()
    client.raise_request_exception = False
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


# ─── Карта прав: провижининг принимает только каталог ERP ────────────────────────────────────


def test_provision_accepts_every_catalog_permission(service, own_company):
    response = provision(service, permissions=list(ALL_PERMISSIONS))
    assert response.status_code == 201


@pytest.mark.parametrize(
    "code",
    [
        "quote.view",  # коды, которые CRM раньше клала в токен, но которых в ERP нет (S-11)
        "quote.edit",
        "supply.*",
        "quote.*",
        "deal.destroy",
        "QUOTE.BUILD",
        "",
    ],
)
def test_provision_rejects_codes_outside_catalog(service, own_company, code):
    response = provision(service, permissions=["deal.manage", code])
    assert response.status_code == 422
    assert response.json() == {"detail": "VALIDATION_ERROR"}
    assert not CustomUser.objects.filter(email="staff@example.com").exists()
    assert not CrmUserMapping.objects.filter(crm_user_id=7001).exists()


def test_provisioned_role_has_exactly_the_requested_permissions(service, own_company):
    provision(service, permissions=["deal.manage", "quote.build"])
    member = CompanyMember.objects.get(user__email="staff@example.com")
    permissions = {p for role in member.company_roles.all() for p in role.permissions}
    assert permissions == {"deal.manage", "quote.build"}
    assert Permission.QUOTE_VIEW_COST_MARGIN.value not in permissions


# ─── Отзыв: access-токены гаснут (S-6) ───────────────────────────────────────────────────


def test_revoke_kills_already_issued_access_token(service, own_company):
    provision(service)
    access, _ = sso_login()
    assert bearer(access).get(ME_URL).status_code == 200

    assert revoke(service).status_code == 204

    response = bearer(access).get(ME_URL)
    assert response.status_code == 401


def test_revoke_bumps_token_version_even_when_user_is_reactivated(service, own_company):
    """Включённый заново пользователь (повторный провижининг) не воскрешает старый access."""
    provision(service)
    old_access, _ = sso_login()
    revoke(service)

    assert provision(service).status_code == 200  # снова выдан доступ
    assert bearer(old_access).get(ME_URL).status_code == 401

    new_access, _ = sso_login("7001")
    assert bearer(new_access).get(ME_URL).status_code == 200


def test_revoke_blacklists_refresh_tokens(service, own_company):
    provision(service)
    _, refresh = sso_login()
    user = CustomUser.objects.get(email="staff@example.com")
    assert OutstandingToken.objects.filter(user=user).exists()

    revoke(service)

    assert not OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False).exists()
    client = APIClient()
    response = client.post(REFRESH_URL, {"refresh": refresh}, format="json")
    assert response.status_code == 401


def test_revoke_closes_login_and_is_idempotent(service, own_company):
    provision(service)
    assert revoke(service).status_code == 204
    user = CustomUser.objects.get(email="staff@example.com")
    assert user.is_active is False
    version = user.token_version

    assert revoke(service).status_code == 204  # повтор — не ошибка
    user.refresh_from_db()
    assert user.is_active is False
    assert user.token_version >= version  # версия не откатывается

    # SSO-обмен для отозванного — 403 USER_INACTIVE
    response = APIClient().post("/api/v1/auth/sso/exchange/", {"token": sso_token()}, format="json")
    assert response.status_code == 403
    assert response.json() == {"detail": "USER_INACTIVE"}


def test_revoke_unknown_crm_user_is_404(service, own_company):
    response = revoke(service, crm_user_id=999999)
    assert response.status_code == 404
    assert response.json() == {"detail": "NOT_FOUND"}


def test_revoke_does_not_touch_other_users(service, own_company):
    provision(service, crm_user_id=7001, email="staff@example.com")
    provision(service, crm_user_id=7002, email="other@example.com")
    other_access, _ = sso_login("7002")

    revoke(service, 7001)

    assert bearer(other_access).get(ME_URL).status_code == 200
    assert CustomUser.objects.get(email="other@example.com").is_active is True


def test_revoke_requires_service_token(own_company):
    client = APIClient()
    assert client.delete("/api/integration/v1/users/7001/sessions").status_code == 401


def test_revoke_does_not_scan_all_django_sessions(service, own_company):
    """S-6: прежний код перебирал ВСЕ сессии Django; теперь вход гасится на уровне пользователя."""
    provision(service)
    with CaptureQueriesContext(connection) as queries:
        assert revoke(service).status_code == 204
    assert not [q["sql"] for q in queries.captured_queries if "django_session" in q["sql"]]


def test_revoke_writes_sso_revoke_audit(service, own_company):
    provision(service)
    revoke(service)

    entry = ActivityLog.objects.get(event_code="sso.revoke")
    assert entry.action == "sso.revoke"
    assert entry.event_params["crm_user_id"] == 7001
    assert entry.event_params["erp_user_id"] == CustomUser.objects.get(email="staff@example.com").pk
    assert "access" not in str(entry.event_params).lower()  # токенов в аудите нет


def test_access_token_without_version_claim_is_version_zero(own_company):
    """Токены, выпущенные до FIX-11 (без `tv`), равны версии 0: пока доступ не отзывали, они живут."""
    from rest_framework_simplejwt.tokens import RefreshToken

    user = CustomUser.objects.create(username="legacy@example.com", email="legacy@example.com", is_superuser=True)
    refresh = RefreshToken()
    refresh["user_id"] = user.pk
    assert "tv" not in refresh.access_token
    assert bearer(str(refresh.access_token)).get(ME_URL).status_code == 200

    CustomUser.objects.filter(pk=user.pk).update(token_version=1)
    assert bearer(str(refresh.access_token)).get(ME_URL).status_code == 401


# ─── Хвост FIX-13: refresh не продлевается тому, кто больше не сотрудник ─────────────────────


@pytest.fixture
def staff_with_refresh(own_company):
    member_role = WorkspaceRole.objects.get(code="MEMBER")
    user = CustomUser.objects.create_user(email="s@example.com", username="s@example.com", password=HASLO)
    member = CompanyMember.objects.create(user=user, company=own_company, role=member_role, is_primary=True)
    client = APIClient()
    client.raise_request_exception = False
    response = client.post(
        "/api/v1/auth/token/", {"email": "s@example.com", "password": HASLO}, format="json"
    )
    assert response.status_code == 200, response.content
    return user, member, client


def test_refresh_works_for_current_staff(staff_with_refresh):
    _, _, client = staff_with_refresh
    response = client.post(REFRESH_URL, {}, format="json")
    assert response.status_code == 200
    assert "access" in response.json()


def test_refresh_is_not_extended_for_user_who_left_the_team(staff_with_refresh):
    user, member, client = staff_with_refresh
    CompanyMember.objects.filter(pk=member.pk).update(is_active=False)
    before = OutstandingToken.objects.filter(user=user).count()

    response = client.post(REFRESH_URL, {}, format="json")

    assert response.status_code == 403
    assert response.json() == {"detail": "STAFF_ONLY"}
    assert OutstandingToken.objects.filter(user=user).count() == before  # новый refresh не выдан
    cookie = response.cookies.get(django_settings.REFRESH_COOKIE_NAME)
    assert cookie is None or cookie.value == ""  # cookie сброшена, не продлена


def test_refresh_is_not_extended_for_client_company_member(own_company):
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client"})[0]
    client_company = Company.objects.create(name="Клиент", inn="500000002")
    client_company.types.add(client_type)
    user = CustomUser.objects.create_user(email="c@example.com", username="c@example.com", password="x")
    CompanyMember.objects.create(
        user=user, company=client_company, role=WorkspaceRole.objects.get(code="MEMBER"), is_primary=True
    )
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)  # выдан до FIX-13

    api = APIClient()
    api.raise_request_exception = False
    response = api.post(REFRESH_URL, {"refresh": str(refresh)}, format="json")

    assert response.status_code == 403
    assert response.json() == {"detail": "STAFF_ONLY"}
    assert "access" not in response.json()


def test_refresh_with_stale_token_version_is_401(staff_with_refresh):
    user, _, client = staff_with_refresh
    CustomUser.objects.filter(pk=user.pk).update(token_version=5)
    response = client.post(REFRESH_URL, {}, format="json")
    assert response.status_code == 401
    assert response.json() == {"detail": "INVALID_REFRESH_TOKEN"}


def test_blacklisted_refresh_is_still_401_after_staff_check(staff_with_refresh):
    user, _, client = staff_with_refresh
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
    assert client.post(REFRESH_URL, {}, format="json").status_code == 401


# ─── Переключатель в шапке ERP — только у пользователя с сопоставлением CRM ────────────────


def test_me_exposes_crm_access_only_for_mapped_user(service, own_company):
    provision(service)
    access, _ = sso_login()
    mapped = bearer(access).get(USERS_ME_URL).json()["capabilities"]
    assert mapped["crm_access"] is True
    assert mapped["sso_enabled"] is True

    local = CustomUser.objects.create_superuser(email="root@example.com", username="root", password=HASLO)
    api = APIClient()
    api.force_authenticate(local)
    unmapped = api.get(USERS_ME_URL).json()["capabilities"]
    assert unmapped["crm_access"] is False
