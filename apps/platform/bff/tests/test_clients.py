"""Клиенты CRM и ERP: таймауты (CRM — из настройки, по умолчанию 5 с) и проброс X-Request-Id."""

import httpx
import respx
from fastapi import FastAPI

from app.clients import CrmClient, ErpClient
from app.clients.base import CRM_TIMEOUT_SECONDS, TIMEOUT_SECONDS
from app.config import Settings
from app.deps import get_redis
from app.main import create_app
from tests.consts import CRM_URL, ERP_URL


def test_crm_timeout_is_five_seconds_by_default() -> None:
    assert CRM_TIMEOUT_SECONDS == 5.0
    assert CrmClient(CRM_URL).http.timeout == httpx.Timeout(5.0)


def test_erp_timeout_stays_three_seconds() -> None:
    assert TIMEOUT_SECONDS == 3.0
    assert ErpClient(ERP_URL).http.timeout == httpx.Timeout(3.0)


async def test_app_builds_crm_client_with_default_timeout(app: FastAPI) -> None:
    assert app.state.crm.http.timeout == httpx.Timeout(5.0)
    assert app.state.erp.http.timeout == httpx.Timeout(3.0)


async def test_app_builds_crm_client_with_timeout_from_settings(settings: Settings) -> None:
    custom = settings.model_copy(update={"crm_timeout_seconds": 9.0})
    application = create_app(custom)
    async with application.router.lifespan_context(application):
        assert application.state.crm.http.timeout == httpx.Timeout(9.0)
        assert application.state.erp.http.timeout == httpx.Timeout(3.0)


@respx.mock
async def test_request_id_forwarded_to_crm_and_erp(app: FastAPI, client: httpx.AsyncClient) -> None:
    class Up:
        async def ping(self) -> bool:
            return True

    app.dependency_overrides[get_redis] = lambda: Up()
    crm_route = respx.get(f"{CRM_URL}/health").respond(200)
    erp_route = respx.get(f"{ERP_URL}/health/").respond(200)

    await client.get("/api/v1/health", headers={"X-Request-Id": "trace-42"})

    assert crm_route.calls.last.request.headers["x-request-id"] == "trace-42"
    assert erp_route.calls.last.request.headers["x-request-id"] == "trace-42"


@respx.mock
async def test_generated_request_id_when_absent(app: FastAPI, client: httpx.AsyncClient) -> None:
    class Up:
        async def ping(self) -> bool:
            return True

    app.dependency_overrides[get_redis] = lambda: Up()
    crm_route = respx.get(f"{CRM_URL}/health").respond(200)
    respx.get(f"{ERP_URL}/health/").respond(200)

    response = await client.get("/api/v1/health")

    generated = response.headers["x-request-id"]
    assert generated
    assert crm_route.calls.last.request.headers["x-request-id"] == generated


@respx.mock
async def test_erp_client_is_healthy_only_on_200() -> None:
    erp = ErpClient(ERP_URL)
    respx.get(f"{ERP_URL}/health/").respond(503)
    assert await erp.is_healthy() is False
    respx.get(f"{ERP_URL}/health/").respond(200)
    assert await erp.is_healthy() is True
    await erp.aclose()
