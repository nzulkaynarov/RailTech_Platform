"""FIX-15: cookie сессии портала для Telegram Mini App (SameSite=None; Secure) и источники CORS."""

import json
import os
import pathlib
import subprocess
import sys
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from portal.models import MagicLinkToken
from portal.services.tokens import generate_token, hash_token
from portal.tests.conftest import make_telegram_init_data

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]
COOKIE = "portal_session"


def sign_in(client, bot_token, contact):
    init_data = make_telegram_init_data(user_id=contact.telegram_user_id, bot_token=bot_token)
    return client.post("/api/portal/v1/auth/telegram", {"init_data": init_data}, format="json")


@pytest.mark.django_db
class TestPortalCookie:
    def test_default_is_lax_httponly_on_portal_path(self, bot_token, client_contact, anon_portal_client):
        morsel = sign_in(anon_portal_client, bot_token, client_contact).cookies[COOKIE]

        assert morsel["samesite"] == "Lax"
        assert morsel["httponly"] is True
        assert morsel["path"] == "/api/portal"

    def test_setting_none_gives_samesite_none_and_secure_even_in_debug(
        self, settings, bot_token, client_contact, anon_portal_client
    ):
        """Mini App — iframe Telegram, другой сайт: без `SameSite=None; Secure` браузер cookie не отдаёт."""
        settings.DEBUG = True
        settings.PORTAL_COOKIE_SAMESITE = "None"

        morsel = sign_in(anon_portal_client, bot_token, client_contact).cookies[COOKIE]

        assert morsel["samesite"] == "None"
        assert morsel["secure"] is True
        assert morsel["httponly"] is True

    def test_magic_link_exchange_uses_the_same_setting(self, settings, client_contact, anon_portal_client):
        settings.PORTAL_COOKIE_SAMESITE = "None"
        raw = generate_token()
        MagicLinkToken.objects.create(
            token_hash=hash_token(raw), contact=client_contact, expires_at=timezone.now() + timedelta(minutes=15)
        )

        morsel = anon_portal_client.post("/api/portal/v1/auth/magic", {"token": raw}, format="json").cookies[COOKIE]

        assert morsel["samesite"] == "None" and morsel["secure"] is True

    def test_lax_stays_not_secure_in_debug_and_secure_outside_it(
        self, settings, bot_token, client_contact, anon_portal_client
    ):
        settings.DEBUG = True
        assert sign_in(anon_portal_client, bot_token, client_contact).cookies[COOKIE]["secure"] == ""
        settings.DEBUG = False
        assert sign_in(anon_portal_client, bot_token, client_contact).cookies[COOKIE]["secure"] is True

    def test_logout_deletes_cookie_with_the_same_attributes(self, settings, portal_client):
        """Cookie с SameSite=None браузер примет к удалению только как `SameSite=None; Secure`."""
        settings.PORTAL_COOKIE_SAMESITE = "None"

        morsel = portal_client.post("/api/portal/v1/auth/logout").cookies[COOKIE]

        assert morsel.value == ""
        assert morsel["samesite"] == "None"
        assert morsel["secure"] is True

    def test_settings_default_is_lax(self):
        assert settings.PORTAL_COOKIE_SAMESITE == "Lax"


def load_settings(**env) -> dict:
    """Настройки в чистом процессе: CORS и cookie считаются при импорте, `override_settings` их не пересчитает."""
    code = (
        "import json, django;"
        "from django.conf import settings;"
        "print(json.dumps({"
        "'allow_all': settings.CORS_ALLOW_ALL_ORIGINS,"
        "'origins': settings.CORS_ALLOWED_ORIGINS,"
        "'cabinet_origins': settings.CABINET_ORIGINS,"
        "'samesite': settings.PORTAL_COOKIE_SAMESITE,"
        "}))"
    )
    base = {k: v for k, v in os.environ.items() if k not in ("DJANGO_DEBUG", "CABINET_URL", "CABINET_ORIGIN")}
    base.update(
        DJANGO_SETTINGS_MODULE="core.settings",
        DJANGO_SECRET_KEY="test-only-secret-key-not-for-production",
        SERVICE_TOKEN_CRM_TO_ERP="test-service-token",
        ERP_WEBHOOK_SECRET="test-webhook-secret",
        ERP_MCP_CONTEXT_KEY="test-mcp-context-key",
        PLATFORM_SSO_SECRET="test-sso-secret",
        MINIO_ENDPOINT="http://rustfs:9000",  # вне DEBUG без S3 ERP не стартует (S0-1)
        MINIO_ACCESS_KEY="test-access",
        MINIO_SECRET_KEY="test-secret",
    )
    base.update(env)
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, env=base, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


DEV_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://cabinet.localhost",
}


class TestCorsOrigins:
    def test_debug_true_allows_dev_origins(self):
        loaded = load_settings(DJANGO_DEBUG="true", CABINET_URL="https://cabinet.example.uz")

        assert loaded["allow_all"] is True
        assert DEV_ORIGINS <= set(loaded["origins"])
        assert "https://cabinet.example.uz" in loaded["origins"]

    def test_debug_false_has_no_dev_origins_and_no_wildcard(self):
        loaded = load_settings(
            DJANGO_DEBUG="false",
            CABINET_URL="https://cabinet.example.uz/",
            CORS_ALLOWED_ORIGINS="https://extra.example.uz",
        )

        assert loaded["allow_all"] is False
        assert loaded["cabinet_origins"] == ["https://cabinet.example.uz"]
        assert loaded["origins"] == ["https://cabinet.example.uz", "https://extra.example.uz"]
        assert not DEV_ORIGINS & set(loaded["origins"])
        assert not [o for o in loaded["origins"] if "localhost" in o or "127.0.0.1" in o]

    def test_cabinet_origin_setting_wins_over_cabinet_url(self):
        loaded = load_settings(
            DJANGO_DEBUG="false", CABINET_URL="https://cabinet.example.uz", CABINET_ORIGIN="https://app.example.uz"
        )

        assert loaded["origins"] == ["https://app.example.uz"]

    def test_cabinet_origin_accepts_a_comma_separated_list_like_crm(self):
        loaded = load_settings(
            DJANGO_DEBUG="false", CABINET_ORIGIN="https://a.example.uz/, https://b.example.uz:8443,https://a.example.uz"
        )

        assert loaded["origins"] == ["https://a.example.uz", "https://b.example.uz:8443"]

    def test_cabinet_origin_is_derived_from_cabinet_url_without_path(self):
        loaded = load_settings(DJANGO_DEBUG="false", CABINET_URL="https://cabinet.example.uz:8443/some/path")

        assert loaded["origins"] == ["https://cabinet.example.uz:8443"]

    def test_samesite_setting_is_read_and_normalised(self):
        assert load_settings(DJANGO_DEBUG="true", PORTAL_COOKIE_SAMESITE="none")["samesite"] == "None"
        assert load_settings(DJANGO_DEBUG="true")["samesite"] == "Lax"

    def test_unknown_samesite_value_stops_startup(self):
        with pytest.raises(AssertionError, match="PORTAL_COOKIE_SAMESITE"):
            load_settings(DJANGO_DEBUG="true", PORTAL_COOKIE_SAMESITE="whatever")
