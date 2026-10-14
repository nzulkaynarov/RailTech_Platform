"""`GET /api/v1/admin/ai-spend` (M3-CRM-09): журнал LiteLLM через respx, права, бюджеты, ошибки."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration

URL = "/api/v1/admin/ai-spend"
FIXTURE = Path(__file__).parents[1] / "fixtures" / "litellm" / "spend_logs_v2.json"


def todays_page() -> dict[str, Any]:
    """Записанный ответ LiteLLM v1.105.0, сдвинутый на «сейчас»: отчёт берёт сутки по Ташкенту."""
    page: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))["page"]
    now = datetime.now(UTC).isoformat()
    page["data"] = [{**row, "startTime": now} for row in page["data"]]
    return page


@pytest.fixture
def logs_url(live_settings: Settings) -> str:
    """Журнал LiteLLM по адресу из окружения тестов (`LITELLM_BASE_URL`), под respx."""
    return f"{str(live_settings.litellm_base_url).rstrip('/')}/spend/logs/v2"


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    app = create_app(live_settings)
    with TestClient(app) as test_client:
        app.state.bot = None
        yield test_client


async def headers(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> dict[str, str]:
    account, password = await make_user(sessions, f"{role}@railtech.uz", [role])
    return login(client, account.email, password)


@pytest.mark.parametrize(("role", "status"), [("manager", 403), ("viewer", 403)])
async def test_only_admin(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str, status: int
) -> None:
    assert client.get(URL).status_code == 401
    auth = await headers(sessions, client, role)
    assert client.get(URL, headers=auth).status_code == status


@respx.mock
async def test_admin_sees_ensemble_spend_and_erp_overrun(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, logs_url: str
) -> None:
    page = todays_page()
    route = respx.get(logs_url).mock(return_value=httpx.Response(200, json=page))
    auth = await headers(sessions, client, "admin")
    budget = {"daily_usd": 2.0, "erp_daily_usd": 0.00001}
    assert client.put("/api/v1/settings/budget", json=budget, headers=auth).status_code == 200

    response = client.get(URL, params={"group": "system"}, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "authorization" in route.calls.last.request.headers
    assert body["totals"]["calls"] == page["total"]
    assert body["totals"]["cost_usd"] == pytest.approx(sum(r["spend"] for r in page["data"]))
    assert body["totals"]["fallback_calls"] == 2
    assert [r["key"] for r in body["rows"]] == ["crm", "erp", "other"]
    erp = next(s for s in body["systems"] if s["system"] == "erp")
    assert (erp["daily_usd"], erp["over_today"], erp["connected"]) == (0.00001, True, True)
    assert [o["system"] for o in body["overruns"]] == ["erp"]
    assert body["erp_connected"] is True

    status = client.get("/api/v1/system/status", headers=auth).json()
    ai = next(c for c in status["components"] if c["key"] == "ai_budget")
    assert ai["status"] == "warn"
    assert ai["reason"].startswith("Бюджет превышен: ERP.")


@respx.mock
async def test_gateway_down_is_502_and_bad_period_is_422(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, logs_url: str
) -> None:
    respx.get(logs_url).mock(return_value=httpx.Response(500, json={"error": {"message": "db"}}))
    auth = await headers(sessions, client, "admin")
    down = client.get(URL, headers=auth)
    assert down.status_code == 502
    assert down.json()["details"]["reason"] == "litellm_unavailable"

    long = client.get(URL, params={"from": "2026-01-01", "to": "2026-10-01"}, headers=auth)
    assert long.status_code == 422
    assert long.json()["details"] == {"reason": "ai_spend_period", "field": "from"}

    status = client.get("/api/v1/system/status", headers=auth).json()
    ai = next(c for c in status["components"] if c["key"] == "ai_budget")
    assert ai["status"] == "unknown"
