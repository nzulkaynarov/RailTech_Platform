"""«Подключения»: матрица ролей, токен шифруется и не возвращается, канал из `my_chat_member`."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.integrations.telegram import BotIdentity, InvalidBotTokenError
from app.main import create_app
from app.models.auth import AuditLog
from app.models.integrations import IntegrationSecret
from app.repositories import telegram_chats
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration

TOKEN = "123456:integration-fake-token-WxYz"  # фиктивный токен, в Telegram не уходит
URL = "/api/v1/integrations/telegram"


class FakeProbe:
    async def get_me(self, token: str) -> BotIdentity:
        if token != TOKEN:
            raise InvalidBotTokenError("401")
        return BotIdentity(id=1, username="railtech_it_bot")


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr("k" * 64)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        app.state.bot = None  # без настоящего Telegram: перезапуск бота не нужен
        app.state.telegram_probe = FakeProbe()
        yield test_client


async def headers(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> dict[str, str]:
    account, password = await make_user(sessions, f"{role}@railtech.uz", [role])
    return login(client, account.email, password)


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_non_admin_forbidden(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> None:
    auth = await headers(sessions, client, role)
    assert client.get(URL, headers=auth).status_code == 403
    body = {"token": TOKEN, "password": PASSWORD}
    assert client.put(f"{URL}/token", json=body, headers=auth).status_code == 403


async def test_token_saved_encrypted_and_never_returned(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await headers(sessions, client, "admin")
    wrong = client.put(f"{URL}/token", json={"token": TOKEN, "password": "nope"}, headers=auth)
    assert wrong.json()["details"]["reason"] == "wrong_password"
    bad = {"token": "999999:rejected-token-value-0000", "password": PASSWORD}
    rejected = client.put(f"{URL}/token", json=bad, headers=auth)
    assert rejected.status_code == 422
    assert rejected.json()["details"]["reason"] == "invalid_bot_token"

    ok = client.put(f"{URL}/token", json={"token": TOKEN, "password": PASSWORD}, headers=auth)
    assert ok.status_code == 200, ok.text
    assert TOKEN not in ok.text
    status = client.get(URL, headers=auth).json()
    assert status["last4"] == "WxYz"
    assert status["configured"] is True
    async with sessions() as session:
        row = (await session.execute(select(IntegrationSecret))).scalar_one()
        audits = (await session.execute(select(AuditLog))).scalars().all()
    assert TOKEN.encode() not in row.ciphertext
    assert all(TOKEN not in repr((a.before, a.after)) for a in audits)


async def test_detected_channel_connects(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await headers(sessions, client, "admin")
    async with sessions() as session, session.begin():
        await telegram_chats.upsert(session, -1001234567890, "Команда RailTech", "channel")
    channels: list[dict[str, Any]] = client.get(f"{URL}/channels", headers=auth).json()
    assert [c["chat_id"] for c in channels] == [-1001234567890]
    assert client.post(f"{URL}/channels/-100999/connect", headers=auth).status_code == 404
    connected = client.post(f"{URL}/channels/-1001234567890/connect", headers=auth)
    assert connected.status_code == 200
    status = client.get(URL, headers=auth).json()
    assert status["channel_id"] == -1001234567890
    assert status["channel_title"] == "Команда RailTech"
