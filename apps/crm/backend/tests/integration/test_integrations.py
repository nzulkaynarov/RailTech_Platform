"""«Подключения»: матрица ролей, секреты шифруются и не возвращаются, канал из `my_chat_member`."""

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
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


# --- Коннектор «ERP» (M3-CRM-02) -----------------------------------------------------------

ERP_URL = "/api/v1/integrations/erp"
ERP_TOKEN = "integration-erp-service-token-Ab12"  # фиктивный, в сеть не уходит
ERP_HOOK = "integration-erp-webhook-secret-Cd34"  # фиктивный
ERP_HEALTH = {
    "status": "ok",
    "version": "test",
    "migrations_applied": True,
    "queue_alive": True,
    "checked_at": "2026-10-13T09:00:00+05:00",
}


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_erp_non_admin_forbidden(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> None:
    auth = await headers(sessions, client, role)
    assert client.get(ERP_URL, headers=auth).status_code == 403
    body = {"base_url": "https://erp.example", "service_token": ERP_TOKEN, "password": PASSWORD}
    assert client.put(ERP_URL, json=body, headers=auth).status_code == 403
    assert client.post(f"{ERP_URL}/check", headers=auth).status_code == 403


async def test_erp_anonymous_unauthorized(client: TestClient) -> None:
    assert client.get(ERP_URL).status_code == 401
    assert client.post(f"{ERP_URL}/check").status_code == 401


@respx.mock
async def test_erp_saved_encrypted_checked_and_audited(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await headers(sessions, client, "admin")
    initial = client.get(ERP_URL, headers=auth).json()
    assert (initial["configured"], initial["mode"]) == (False, "local")
    not_configured = client.post(f"{ERP_URL}/check", headers=auth)
    assert not_configured.status_code == 409
    assert not_configured.json()["details"]["reason"] == "erp_not_configured"

    wrong = client.put(
        ERP_URL, json={"base_url": "https://erp.example", "password": "nope"}, headers=auth
    )
    assert wrong.json()["details"]["reason"] == "wrong_password"
    bad_url = client.put(
        ERP_URL, json={"base_url": "erp.example", "password": PASSWORD}, headers=auth
    )
    assert bad_url.status_code == 422
    assert bad_url.json()["details"] == {"reason": "erp_invalid_url", "field": "base_url"}

    body = {
        "base_url": "https://erp.example/api/integration/v1/",
        "service_token": ERP_TOKEN,
        "webhook_secret": ERP_HOOK,
        "password": PASSWORD,
    }
    saved = client.put(ERP_URL, json=body, headers=auth)
    assert saved.status_code == 200, saved.text
    status = saved.json()
    assert (status["configured"], status["mode"], status["base_url"]) == (
        True,
        "erp",
        "https://erp.example",
    )
    assert (status["token_last4"], status["webhook_secret_last4"]) == ("Ab12", "Cd34")
    assert ERP_TOKEN not in saved.text
    assert ERP_HOOK not in saved.text

    route = respx.get("https://erp.example/api/integration/v1/health").mock(
        return_value=httpx.Response(200, json=ERP_HEALTH)
    )
    checked = client.post(f"{ERP_URL}/check", headers=auth)
    assert checked.status_code == 200, checked.text
    assert checked.json()["version"] == "test"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {ERP_TOKEN}"

    route.mock(return_value=httpx.Response(401, json={"detail": "UNAUTHORIZED"}))
    rejected = client.post(f"{ERP_URL}/check", headers=auth)
    assert rejected.status_code == 502
    assert rejected.json()["details"]["reason"] == "erp_unauthorized"

    system = client.get("/api/v1/system/status", headers=auth).json()
    erp = next(c for c in system["components"] if c["key"] == "erp")
    assert erp["status"] == "fail"  # последняя проверка — 401, кэш 30 с

    async with sessions() as session:
        rows = (await session.execute(select(IntegrationSecret))).scalars().all()
        audits = (await session.execute(select(AuditLog))).scalars().all()
    assert {r.key for r in rows} >= {"erp_service_token", "erp_webhook_secret"}
    assert all(ERP_TOKEN.encode() not in r.ciphertext for r in rows)
    erp_audits = [a for a in audits if a.action == "integrations.erp"]
    assert len(erp_audits) == 1
    after = erp_audits[0].after
    assert after is not None
    assert after["base_url"] == "https://erp.example"
    assert all(ERP_TOKEN not in repr((a.before, a.after)) for a in audits)


# --- Ротация секрета вебхуков без простоя (FIX-35) --------------------------------------------

EVENTS_URL = "/bus/v1/events"
OLD_HOOK = "integration-erp-webhook-OLD-secret-0001"  # фиктивный
NEW_HOOK = "integration-erp-webhook-NEW-secret-0002"  # фиктивный


def post_event(client: TestClient, secret: str, serial: int) -> int:
    """Событие из примеров контракта, подписанное парой `erp → crm`, выведенной из секрета
    вебхуков (L12); `serial` делает событие новым (иначе это дубль по id).
    """
    from app.bus.secrets import derive_pair_secret
    from tests.bus_events import example_envelope, signed_request

    envelope = example_envelope("uz.railtech.erp.quote.viewed.v1")
    envelope["id"] = str(uuid.uuid4())
    envelope["time"] = f"2026-10-13T06:{serial:02d}:00Z"
    headers, body = signed_request(envelope, derive_pair_secret(secret, "erp", "crm"))
    return client.post(EVENTS_URL, content=body, headers=headers).status_code


async def test_webhook_secret_rotation_without_downtime(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    """Старый секрет принимается, пока он «предыдущий»; снят — 401. Без `.env`, без перезапуска:
    секреты пары шины выводятся из секретов вебхуков и перечитываются при каждом приёме.
    """
    auth = await headers(sessions, client, "admin")

    def save(**fields: Any) -> dict[str, Any]:
        body = {"base_url": "https://erp.example", "password": PASSWORD, **fields}
        response = client.put(ERP_URL, json=body, headers=auth)
        assert response.status_code == 200, response.text
        for secret in (OLD_HOOK, NEW_HOOK):
            assert secret not in response.text
        status: dict[str, Any] = response.json()
        return status

    assert post_event(client, OLD_HOOK, 1) == 401  # секрет ещё не задан: пара не подписывается
    first = save(service_token=ERP_TOKEN, webhook_secret=OLD_HOOK)
    assert first["webhook_secret_previous_configured"] is False
    assert post_event(client, OLD_HOOK, 2) == 200
    assert post_event(client, NEW_HOOK, 3) == 401

    # Шаг 1. В CRM — новый как текущий, старый как предыдущий: принимаются оба.
    rotating = save(webhook_secret=NEW_HOOK, webhook_secret_previous=OLD_HOOK)
    assert rotating["webhook_secret_previous_configured"] is True
    assert rotating["webhook_secret_previous_source"] == "db"
    assert rotating["webhook_secret_previous_last4"] == "0001"
    assert rotating["webhook_secret_last4"] == "0002"
    assert post_event(client, OLD_HOOK, 4) == 200, "ERP ещё подписывает старым"
    assert post_event(client, NEW_HOOK, 5) == 200, "ERP уже подписывает новым"
    assert post_event(client, "some-other-secret-value-0003", 6) == 401

    # Шаг 3. Предыдущий снят: старый секрет — 401, новый — по-прежнему принимается.
    done = save(clear_webhook_secret_previous=True)
    assert done["webhook_secret_previous_configured"] is False
    assert done["webhook_secret_previous_last4"] is None
    assert post_event(client, OLD_HOOK, 7) == 401
    assert post_event(client, NEW_HOOK, 8) == 200

    async with sessions() as session:
        keys = {r.key for r in (await session.execute(select(IntegrationSecret))).scalars()}
        audits = [
            a
            for a in (await session.execute(select(AuditLog))).scalars()
            if a.action == "integrations.erp"
        ]
    assert "erp_webhook_secret_previous" not in keys
    assert len(audits) == 3
    assert all(OLD_HOOK not in repr((a.before, a.after)) for a in audits)
    assert all(NEW_HOOK not in repr((a.before, a.after)) for a in audits)
    last_after = audits[-1].after
    assert last_after is not None
    assert last_after["erp_webhook_secret_previous_last4"] is None


async def test_the_previous_secret_form_field_is_validated(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await headers(sessions, client, "admin")
    body = {
        "base_url": "https://erp.example",
        "webhook_secret_previous": "short",
        "password": PASSWORD,
    }
    assert client.put(ERP_URL, json=body, headers=auth).status_code == 422
    viewer = await headers(sessions, client, "viewer")
    ok = {
        "base_url": "https://erp.example",
        "clear_webhook_secret_previous": True,
        "password": PASSWORD,
    }
    assert client.put(ERP_URL, json=ok, headers=viewer).status_code == 403
