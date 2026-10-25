"""Здоровье, формат ошибок и X-Request-ID (без базы, кроме /health)."""

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from tests.conftest import ACCESS_SECRET, SSO_CURRENT


async def test_unknown_route_uses_error_format(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Не найдено.", "source": "eds"}


async def test_wrong_method_is_bad_request_error(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/sso/exchange")
    assert response.status_code == 405
    assert response.json()["code"] == "BAD_REQUEST"
    assert response.json()["source"] == "eds"


async def test_request_id_is_echoed_or_generated(client: httpx.AsyncClient) -> None:
    given = await client.get("/health", headers={"X-Request-ID": "req-1234.abc"})
    assert given.headers["X-Request-ID"] == "req-1234.abc"
    generated = await client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert generated.headers["X-Request-ID"] != "bad id with spaces"
    assert len(generated.headers["X-Request-ID"]) >= 32


async def test_docs_are_not_served(client: httpx.AsyncClient) -> None:
    assert (await client.get("/docs")).status_code == 404


async def test_health_without_database_is_503() -> None:
    settings = Settings(
        EDS_DATABASE_URL="postgresql+psycopg://nobody:nobody@127.0.0.1:1/none",
        EDS_ACCESS_SECRET=ACCESS_SECRET,
        PLATFORM_SSO_SECRET=SSO_CURRENT,
        health_timeout_s=1,
    )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eds.test") as http,
    ):
        response = await http.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "version": "dev", "checks": {"database": "unavailable"}}


@pytest.mark.pg
async def test_health_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "dev", "checks": {"database": "ok"}}


def test_empty_sso_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="PLATFORM_SSO_SECRET"):
        Settings(EDS_DATABASE_URL="postgresql://x/y", EDS_ACCESS_SECRET=ACCESS_SECRET, PLATFORM_SSO_SECRET=" , ")
