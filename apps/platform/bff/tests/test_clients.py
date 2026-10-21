"""Клиенты CRM и ERP: таймаут 3 с и проброс X-Request-Id."""

import httpx
import respx
from fastapi import FastAPI

from app.clients import CrmClient, ErpClient
from app.clients.base import TIMEOUT_SECONDS
from app.deps import get_redis
from tests.conftest import CRM_URL, ERP_URL


def test_timeout_is_three_seconds() -> None:
    crm = CrmClient(CRM_URL)
    assert TIMEOUT_SECONDS == 3.0
    assert crm.http.timeout == httpx.Timeout(3.0)


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
