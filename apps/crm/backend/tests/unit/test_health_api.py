from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.api.health import get_readiness
from app.config import Settings
from app.main import create_app
from app.services.readiness import ReadinessService


async def ok() -> None:
    return None


async def boom() -> None:
    raise ConnectionError("down")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_health_is_always_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("s3_probe", "status_code", "body"),
    [
        (ok, 200, {"status": "ok", "checks": {"database": "ok", "s3": "ok"}}),
        (boom, 503, {"status": "fail", "checks": {"database": "ok", "s3": "fail"}}),
    ],
)
def test_ready_reflects_probes(
    client: TestClient, s3_probe: object, status_code: int, body: dict[str, object]
) -> None:
    service = ReadinessService({"database": ok, "s3": s3_probe}, timeout_s=0.5)  # type: ignore[dict-item]
    client.app.dependency_overrides[get_readiness] = lambda: service  # type: ignore[attr-defined]
    response = client.get("/ready")
    assert response.status_code == status_code
    assert response.json() == body


@respx.mock
def test_ready_wires_real_probes(client: TestClient) -> None:
    respx.get("http://s3.invalid:9000/health").mock(httpx.Response(200))
    respx.get("http://litellm.invalid:4000/health/liveliness").mock(httpx.Response(500))
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "fail", "s3": "ok", "litellm": "fail"}


def test_request_id_is_echoed(client: TestClient) -> None:
    request_id = "8c4a3b8e-0a52-4b7e-9e64-3b1a2b5c6d7e"
    response = client.get("/health", headers={"X-Request-ID": request_id})
    assert response.headers["X-Request-ID"] == request_id


def test_request_id_is_generated_when_missing(client: TestClient) -> None:
    response = client.get("/health")
    assert len(response.headers["X-Request-ID"]) == 32
