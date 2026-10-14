import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, SystemRole, WorkspaceRole

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_default_cache():
    """Hermetic tests: flush the default cache before every test.

    The default cache is real Redis (DB0), shared with the DRF throttle
    scopes, the SEC-06 login lockout, and the 2FA replay guards (used-ticket /
    used-code markers). Without this, throttle counters and replay markers
    persist across tests AND across local runs (their TTLs outlive a run),
    so re-running the suite locally spuriously trips the login/password
    throttles. CI uses ephemeral Redis and never saw it; this makes local
    runs match CI.
    """
    from django.core.cache import cache

    cache.clear()
    yield


@pytest.fixture
def api_client():
    """REST API client for making requests."""
    return APIClient()


@pytest.fixture
def authenticated_client(api_client, user_factory):
    """API client with authenticated user."""
    user = user_factory()
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return api_client


@pytest.fixture
def user_factory(db):
    """Factory for creating test users."""

    def create_user(
        email="testuser@example.com",
        username="testuser",
        password="testpass123",
        first_name="Test",
        last_name="User",
        is_active=True,
        is_staff=False,
    ):
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
            is_staff=is_staff,
        )
        return user

    return create_user


@pytest.fixture
def company_factory(db):
    """Factory for creating test companies."""

    def create_company(
        name="Test Company",
        inn="1234567890",
        email="company@example.com",
        phone="+1234567890",
        legal_address="123 Main St",
        website="https://example.com",
        country=None,
    ):
        return Company.objects.create(
            name=name,
            inn=inn,
            email=email,
            phone=phone,
            legal_address=legal_address,
            website=website,
            country=country,
        )

    return create_company


@pytest.fixture
def system_role_factory(db):
    """Factory for creating system roles. Canonical: ADMIN, USER."""

    def create_role(code="USER", name="User"):
        role, _ = SystemRole.objects.get_or_create(
            code=code,
            defaults={"name": name},
        )
        return role

    return create_role


@pytest.fixture
def workspace_role_factory(db):
    """Factory for creating workspace roles."""

    def create_role(code="OWNER", name="Owner"):
        role, _ = WorkspaceRole.objects.get_or_create(code=code, defaults={"name": name})
        return role

    return create_role


@pytest.fixture
def authenticated_user(user_factory):
    """Create a default authenticated user."""
    return user_factory(email="auth@example.com", username="authuser", password="authpass123")


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Install pgtrigger triggers, the pghistory context stub, and pg_trgm.

    --nomigrations short-circuits migrations so pgtrigger/pghistory schema
    objects and the pg_trgm extension (created in migration catalog/0006) are
    never installed. We install them once per session so business-logic tests
    that trigger INSERT...DealEvent (pghistory snapshot triggers) don't fail with
    "_pgh_attach_context() does not exist", and Smart-Match / AI-shortlist tests
    that call SIMILARITY() don't fail with "function similarity(...) does not exist".
    """
    from django.db import connection

    with django_db_blocker.unblock():
        with connection.cursor() as c:
            # Trigram similarity backs Smart Match + the AI catalog shortlist.
            c.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            c.execute(
                "CREATE OR REPLACE FUNCTION _pgh_attach_context() "
                "RETURNS uuid AS $$ SELECT NULL::uuid $$ LANGUAGE sql"
            )
        try:
            import pgtrigger

            pgtrigger.install()
        except Exception:
            pass
