"""«Состояние системы» не ждёт медленный источник (W15b-1, гейт W15: карточка в загрузке)."""

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    app = create_app(live_settings)
    with TestClient(app) as test_client:
        app.state.bot = None
        yield test_client


class _Hanging:
    """Источник, который не отвечает: проба ERP, журнал расходов, сводка внешних сервисов."""

    async def hang(self, *args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(60)

    health_facts = hang
    today_facts = hang
    summary = hang
    get = hang  # настройки из БД
    status = hang  # бакет резервных копий


async def test_hanging_sources_give_not_checked_rows_and_the_card_still_answers(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    auth = login(client, account.email, password)
    monkeypatch.setattr("app.api.v1.system_status.SOURCE_TIMEOUT_S", 0.2)
    monkeypatch.setattr("app.services.system_status.SOURCE_TIMEOUT_S", 0.2)
    container = client.app.state.container  # type: ignore[attr-defined]
    hanging = _Hanging()
    container.__dict__["erp_connector"] = hanging
    container.__dict__["ai_spend"] = hanging
    container.__dict__["external_view"] = hanging

    started = time.monotonic()
    response = client.get("/api/v1/system/status", headers=auth)
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert elapsed < 1.0, (
        elapsed
    )  # при пределе 0,2 с карточка отвечает сразу, а не ждёт 60 с зависшего
    rows = {c["key"]: c for c in response.json()["components"]}
    for key in ("erp", "ai_budget", "external_services"):
        assert rows[key]["status"] == "unknown", key
    assert "не ответил в срок" in rows["erp"]["reason"]
    assert "не ответил в срок" in rows["external_services"]["reason"]
    # остальные строки на месте: зависимости, секреты, бот
    assert {"secrets", "bot"} <= set(rows)


async def test_hanging_database_part_and_backup_bucket_are_their_own_not_checked_rows(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    auth = login(client, account.email, password)
    monkeypatch.setattr("app.api.v1.system_status.SOURCE_TIMEOUT_S", 0.2)
    monkeypatch.setattr("app.services.system_status.SOURCE_TIMEOUT_S", 0.2)
    container = client.app.state.container  # type: ignore[attr-defined]
    hanging = _Hanging()
    container.__dict__["settings_service"] = hanging  # данные из БД (модели, очередь, канал)
    container.__dict__["backup_service"] = hanging  # бакет резервных копий

    started = time.monotonic()
    response = client.get("/api/v1/system/status", headers=auth)
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert elapsed < 1.0, elapsed
    rows = {c["key"]: c for c in response.json()["components"]}
    assert rows["state_db"]["status"] == "unknown"
    assert rows["backup"]["status"] == "unknown"
    assert "не ответил в срок" in rows["backup"]["reason"]
    assert "secrets" in rows  # остальные строки на месте
