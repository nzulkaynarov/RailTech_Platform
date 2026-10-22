"""Связь `crm-api` ↔ `crm-bot` через БД (S0-4): статус, пульс, запрос на перезапуск."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.profile import ProfilePublish
from app.config import Settings
from app.integrations.telegram import BotIdentity
from app.main import create_app
from app.services.bot_state import BotStateService
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration

TOKEN = "123456:integration-fake-token-WxYz"  # фиктивный токен, в Telegram не уходит
URL = "/api/v1/integrations/telegram"


async def report(state: BotStateService, **override: object) -> None:
    values: dict[str, object] = {
        "running": True,
        "mode": "polling",
        "source": "db",
        "username": "railtech_it_bot",
        "last_error": None,
        "profile": None,
    }
    await state.report(**{**values, **override})  # type: ignore[arg-type]


async def test_no_record_until_crm_bot_reports(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert await BotStateService(sessions).snapshot() is None


async def test_report_is_visible_to_api_and_goes_stale_without_pulse(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    state = BotStateService(sessions, stale_after_s=45)
    await report(state)
    snapshot = await state.snapshot()
    assert snapshot is not None
    assert (snapshot.alive, snapshot.running, snapshot.username) == (True, True, "railtech_it_bot")

    # Процесс crm-bot остановили: пульса нет — «работает» недостоверно, имя бота не показываем.
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE bot_runtime SET heartbeat_at = now() - interval '2 minutes'")
        )
    stale = await state.snapshot()
    assert stale is not None
    assert (stale.alive, stale.running, stale.username) == (False, False, None)

    await report(state)  # процесс вернулся
    assert (await state.snapshot()).alive is True  # type: ignore[union-attr]


async def test_graceful_stop_is_visible_at_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    state = BotStateService(sessions)
    await report(state)
    await state.mark_stopped()
    snapshot = await state.snapshot()
    assert snapshot is not None
    assert (snapshot.alive, snapshot.running) == (False, False)


async def test_restart_request_is_applied_exactly_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    state = BotStateService(sessions)
    async with sessions() as session, session.begin():
        first = await state.request_restart(session)
    pending = await state.pending_restart()
    assert pending.pending
    assert pending.requested_at == first

    await state.mark_applied(first)
    assert not (await state.pending_restart()).pending

    # Новый запрос после выполненного снова виден; применённая метка не затирается отчётом.
    async with sessions() as session, session.begin():
        second = await state.request_restart(session)
    await report(state)
    pending = await state.pending_restart()
    assert pending.pending
    assert pending.requested_at == second
    assert pending.applied_at == first


async def test_wait_applied_returns_when_crm_bot_confirms(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    state = BotStateService(sessions)
    async with sessions() as session, session.begin():
        requested = await state.request_restart(session)

    async def crm_bot() -> None:
        await asyncio.sleep(0.4)
        await state.mark_applied(requested)

    task = asyncio.create_task(crm_bot())
    assert await state.wait_applied(requested, timeout_s=5) is True
    await task


async def test_wait_applied_gives_up_when_crm_bot_is_down(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    state = BotStateService(sessions)
    async with sessions() as session, session.begin():
        requested = await state.request_restart(session)
    assert await state.wait_applied(requested, timeout_s=0.5) is False


async def test_profile_result_survives_between_processes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    state = BotStateService(sessions)
    result = ProfilePublish(ok=True, at=datetime(2026, 10, 23, 9, 0, tzinfo=UTC), changed=2)
    await state.record_profile(result)
    await report(state)  # отчёт crm-bot без профиля не стирает результат публикации из API
    snapshot = await state.snapshot()
    assert snapshot is not None
    assert snapshot.profile == result


# --- через HTTP API ------------------------------------------------------------------------------


class FakeProbe:
    async def get_me(self, token: str) -> BotIdentity:
        return BotIdentity(id=1, username="railtech_it_bot")


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(
        update={"secrets_key": SecretStr("k" * 64), "bot_restart_wait_s": 0.0}
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        app.state.telegram_probe = FakeProbe()
        yield test_client


async def test_api_has_no_bot_and_no_webhook(client: TestClient) -> None:
    assert not hasattr(client.app.state, "bot")  # type: ignore[attr-defined]
    response = client.post(
        "/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "anything"},
    )
    assert response.status_code == 404


async def test_saving_token_asks_crm_bot_to_restart_and_status_follows_it(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    account, password = await make_user(sessions, "admin@railtech.uz", ["admin"])
    auth = login(client, account.email, password)
    state = BotStateService(sessions)

    before = client.get(URL, headers=auth).json()
    assert before["running"] is False
    assert before["last_error"] == "bot_process_never_started"

    ok = client.put(f"{URL}/token", json={"token": TOKEN, "password": PASSWORD}, headers=auth)
    assert ok.status_code == 200, ok.text
    assert TOKEN not in ok.text
    pending = await state.pending_restart()
    assert pending.pending  # API бота не трогает: только записала просьбу в БД

    # crm-bot замечает просьбу, перезапускается и сообщает новый статус.
    assert pending.requested_at is not None
    await report(state, source="db")
    await state.mark_applied(pending.requested_at)
    status = client.get(URL, headers=auth).json()
    assert (status["running"], status["username"], status["source"]) == (
        True,
        "railtech_it_bot",
        "db",
    )
    assert not (await state.pending_restart()).pending

    components = {
        c["key"]: c for c in client.get("/api/v1/system/status", headers=auth).json()["components"]
    }
    assert components["bot"]["status"] == "ok"

    # crm-bot остановлен: «Состояние системы» и «Подключения» говорят правду.
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE bot_runtime SET heartbeat_at = now() - interval '5 minutes'")
        )
    down = client.get(URL, headers=auth).json()
    assert (down["running"], down["last_error"]) == (False, "bot_process_down")
    components = {
        c["key"]: c for c in client.get("/api/v1/system/status", headers=auth).json()["components"]
    }
    assert components["bot"]["status"] == "fail"
    assert "crm-bot" in components["bot"]["reason"]
