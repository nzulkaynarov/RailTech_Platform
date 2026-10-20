"""Секреты шва CRM ↔ ERP без значений по умолчанию (FIX-01, аудит S-1, I-1).

Известный всем ключ в коде = открытый шов: подделка SSO-входа, вызовов интеграции, контекста MCP
и вебхуков. Поэтому: без DEBUG старт без секрета падает, при DEBUG пустой секрет закрывает функцию.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from rest_framework.test import APIClient

SEAM_SECRETS = ("SERVICE_TOKEN_CRM_TO_ERP", "ERP_WEBHOOK_SECRET", "ERP_MCP_CONTEXT_KEY", "PLATFORM_SSO_SECRET")
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _start_django(extra_env: dict) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key not in SEAM_SECRETS}
    env.update({"DJANGO_SETTINGS_MODULE": "core.settings", "DJANGO_SECRET_KEY": "x" * 50, **extra_env})
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_production_start_fails_without_seam_secrets():
    result = _start_django({"DJANGO_DEBUG": "False"})

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    for name in SEAM_SECRETS:
        assert name in result.stderr


def test_production_start_succeeds_with_seam_secrets():
    result = _start_django({"DJANGO_DEBUG": "False", **{name: f"value-of-{name.lower()}" for name in SEAM_SECRETS}})

    assert result.returncode == 0, result.stderr


@pytest.fixture
def no_seam_secrets(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = []
    settings.ERP_WEBHOOK_SECRET = ""
    settings.ERP_MCP_CONTEXT_KEY = ""
    settings.PLATFORM_SSO_SECRET = []


@pytest.mark.django_db
def test_integration_api_is_closed_without_service_token(no_seam_secrets):
    response = APIClient().get("/api/integration/v1/health", HTTP_AUTHORIZATION="Bearer test-crm-to-erp-token")

    assert response.status_code == 401


@pytest.mark.django_db
def test_mcp_is_closed_without_context_key(no_seam_secrets):
    from integration.mcp.context import issue_agent_context
    from integration.tests.mcp_support import raw_rpc

    forged = issue_agent_context("", crm_client_id=1, mode="prospect")
    response = raw_rpc(forged, "tools/list")  # erp-mcp (FIX-36) — отдельное приложение SDK, не маршрут Django

    assert response.status_code == 401
    assert response.json() == {"detail": "INVALID_AGENT_CONTEXT"}


@pytest.mark.django_db
def test_mcp_route_is_gone_from_the_django_app():
    assert APIClient().get("/mcp/erp/").status_code == 404


@pytest.mark.django_db
def test_sso_exchange_is_unavailable_without_secret(no_seam_secrets, settings):
    settings.PLATFORM_SSO_ENABLED = True  # флаг FIX-03 включён — проверяем именно отсутствие секрета
    response = APIClient().post("/api/v1/auth/sso/exchange/", {"token": "anything"}, format="json")

    assert response.status_code == 503
    assert response.data["detail"] == "SSO_NOT_CONFIGURED"


@pytest.mark.django_db
def test_webhook_is_not_emitted_without_secret(no_seam_secrets):
    from integration.models import IntegrationWebhookEvent
    from integration.services.webhooks import emit_event

    assert emit_event("deal.stage_changed", erp_company_id=1, payload={}, crm_client_id=1, send_async=False) is None
    assert not IntegrationWebhookEvent.objects.exists()
