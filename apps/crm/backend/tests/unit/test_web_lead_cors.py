"""CORS только для формы «Запрос» (M3-CRM-05): origin из CABINET_ORIGIN, остальной API без."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.cors import WebLeadCorsMiddleware
from app.config import Settings

CABINET = "https://cabinet.railtech.uz"


def _app(origins: list[str]) -> TestClient:
    app = FastAPI()
    app.add_middleware(WebLeadCorsMiddleware, origins=origins)

    @app.get("/api/v1/leads/web/token")
    async def token() -> dict[str, str]:
        return {"token": "x"}

    @app.post("/api/v1/leads/web")
    async def web() -> dict[str, int]:
        return {"lead_id": 1}

    @app.get("/api/v1/leads")
    async def leads() -> list[int]:
        return []

    return TestClient(app)


def test_cabinet_origin_allowed_on_web_form_only() -> None:
    client = _app([CABINET])
    allowed = client.get("/api/v1/leads/web/token", headers={"Origin": CABINET})
    assert allowed.headers.get("access-control-allow-origin") == CABINET
    preflight = client.options(
        "/api/v1/leads/web",
        headers={
            "Origin": CABINET,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == CABINET
    assert "POST" in preflight.headers.get("access-control-allow-methods", "")
    # Остальной API CORS-заголовков не получает даже для разрешённого origin.
    other = client.get("/api/v1/leads", headers={"Origin": CABINET})
    assert other.status_code == 200
    assert "access-control-allow-origin" not in other.headers


def test_foreign_origin_gets_no_cors_headers() -> None:
    client = _app([CABINET])
    response = client.get("/api/v1/leads/web/token", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("https://cabinet.railtech.uz", ["https://cabinet.railtech.uz"]),
        (
            "https://cabinet.railtech.uz/, http://cabinet.localhost ",
            [
                "https://cabinet.railtech.uz",
                "http://cabinet.localhost",
            ],
        ),
    ],
)
def test_cabinet_origins_setting(raw: str, expected: list[str]) -> None:
    assert Settings(_env_file=None, cabinet_origin=raw).cabinet_origins == expected
