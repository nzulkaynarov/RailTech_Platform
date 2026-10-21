"""GET /api/v1/health: схема Health из контракта и все комбинации ok/fail для Redis, CRM, ERP."""

import itertools
from typing import Any

import httpx
import jsonschema
import pytest
import respx
from fastapi import FastAPI

from app.deps import get_redis
from tests.conftest import CRM_URL, ERP_URL


class FakeRedis:
    def __init__(self, *, up: bool) -> None:
        self.up = up

    async def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("redis down")
        return True


def validate_health(contract: dict[str, Any], body: object) -> None:
    schema = contract["components"]["schemas"]["Health"]
    jsonschema.Draft202012Validator(schema).validate(body)


def mock_backends(crm_up: bool, erp_up: bool) -> None:
    respx.get(f"{CRM_URL}/health").respond(200 if crm_up else 503)
    respx.get(f"{ERP_URL}/health/").respond(200 if erp_up else 503)


@pytest.mark.parametrize(
    ("redis_up", "crm_up", "erp_up"), list(itertools.product([True, False], repeat=3))
)
@respx.mock
async def test_health_all_combinations(
    app: FastAPI,
    client: httpx.AsyncClient,
    contract: dict[str, Any],
    redis_up: bool,
    crm_up: bool,
    erp_up: bool,
) -> None:
    app.dependency_overrides[get_redis] = lambda: FakeRedis(up=redis_up)
    mock_backends(crm_up, erp_up)

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    validate_health(contract, body)
    expected = {
        "redis": "ok" if redis_up else "fail",
        "crm": "ok" if crm_up else "fail",
        "erp": "ok" if erp_up else "fail",
    }
    assert body["checks"] == expected
    assert body["status"] == ("ok" if redis_up and crm_up and erp_up else "degraded")


@respx.mock
async def test_health_backend_unreachable_is_degraded(
    app: FastAPI, client: httpx.AsyncClient, contract: dict[str, Any]
) -> None:
    app.dependency_overrides[get_redis] = lambda: FakeRedis(up=True)
    respx.get(f"{CRM_URL}/health").mock(side_effect=httpx.ConnectError("no route"))
    respx.get(f"{ERP_URL}/health/").mock(side_effect=httpx.ReadTimeout("slow"))

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    validate_health(contract, body)
    assert body["status"] == "degraded"
    assert body["checks"] == {"redis": "ok", "crm": "fail", "erp": "fail"}


async def test_health_real_redis_connection_refused(
    client: httpx.AsyncClient, contract: dict[str, Any]
) -> None:
    """Настоящий клиент Redis на закрытом порту, CRM и ERP молчат: 200 degraded, не ошибка."""
    with respx.mock:
        respx.get(f"{CRM_URL}/health").mock(side_effect=httpx.ConnectError("no route"))
        respx.get(f"{ERP_URL}/health/").mock(side_effect=httpx.ConnectError("no route"))
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    validate_health(contract, body)
    assert body == {
        "status": "degraded",
        "checks": {"redis": "fail", "crm": "fail", "erp": "fail"},
        "version": body["version"],
    }


@respx.mock
async def test_health_is_public_and_returns_request_id(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.dependency_overrides[get_redis] = lambda: FakeRedis(up=True)
    mock_backends(True, True)

    response = await client.get("/api/v1/health", headers={"X-Request-Id": "req-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-123"
