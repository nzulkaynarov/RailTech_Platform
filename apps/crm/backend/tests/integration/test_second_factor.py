"""ДВ-4: второй фактор входа на реальном Postgres — настройка, вход с кодом, резервный код,
«запомнить устройство», блокировка за неверные коды, отключение."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pyotp
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr("s" * 64)})
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def enable(client: TestClient, headers: dict[str, str]) -> tuple[str, list[str]]:
    setup = client.post(
        "/api/v1/me/second-factor/setup", json={"issuer": "RailTech"}, headers=headers
    )
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/RailTech:")
    wrong = client.post("/api/v1/me/second-factor/enable", json={"code": "000000"}, headers=headers)
    assert wrong.status_code == 422
    assert wrong.json()["details"]["reason"] == "second_factor_code_invalid"
    enabled = client.post(
        "/api/v1/me/second-factor/enable",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    return secret, enabled.json()["backup_codes"]


def password_step(client: TestClient, email: str, **extra: object) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD, **extra}
    )
    assert response.status_code == 202, response.text
    body: dict[str, object] = response.json()
    assert body["second_factor_required"] is True
    return body


async def test_enable_then_login_needs_a_code(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "tf1@railtech.uz", ["admin"])
    headers = login(client, account.email, PASSWORD)
    secret, backup = enable(client, headers)
    assert len(backup) == 8
    status = client.get("/api/v1/me/second-factor", headers=headers).json()
    assert status["enabled"] is True
    assert status["backup_codes_left"] == 8

    challenge = password_step(client, account.email)["challenge"]
    # тот же код, что включил фактор, второй раз не проходит; ждать шага не нужно — берём следующий
    later = pyotp.TOTP(secret).at(datetime.now(UTC).timestamp() + 30)
    ok = client.post(
        "/api/v1/auth/login/second-factor",
        json={"challenge": challenge, "code": later, "remember_device": True},
    )
    assert ok.status_code == 200, ok.text
    device = ok.json()["device_token"]
    assert device
    assert ok.json()["access_token"]

    remembered = client.post(
        "/api/v1/auth/login",
        json={"email": account.email, "password": PASSWORD, "device_token": device},
    )
    assert remembered.status_code == 200
    assert remembered.json()["device_token"] is None


async def test_backup_code_works_once(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "tf2@railtech.uz", ["manager"])
    _, backup = enable(client, login(client, account.email, PASSWORD))

    challenge = password_step(client, account.email)["challenge"]
    used = client.post(
        "/api/v1/auth/login/second-factor", json={"challenge": challenge, "code": backup[0]}
    )
    assert used.status_code == 200
    challenge = password_step(client, account.email)["challenge"]
    again = client.post(
        "/api/v1/auth/login/second-factor", json={"challenge": challenge, "code": backup[0]}
    )
    assert again.status_code == 401
    assert again.json()["code"] == "second_factor_invalid"


async def test_wrong_codes_lock_the_account(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "tf3@railtech.uz", ["manager"])
    enable(client, login(client, account.email, PASSWORD))
    challenge = password_step(client, account.email)["challenge"]
    codes = [
        client.post(
            "/api/v1/auth/login/second-factor", json={"challenge": challenge, "code": "000000"}
        ).status_code
        for _ in range(10)
    ]
    assert codes == [401] * 9 + [423]


async def test_disable_with_a_code(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "tf4@railtech.uz", ["viewer"])
    headers = login(client, account.email, PASSWORD)
    _, backup = enable(client, headers)
    wrong = client.post(
        "/api/v1/me/second-factor/disable", json={"code": "000000"}, headers=headers
    )
    assert wrong.status_code == 422
    off = client.post("/api/v1/me/second-factor/disable", json={"code": backup[1]}, headers=headers)
    assert off.status_code == 204
    assert client.get("/api/v1/me/second-factor", headers=headers).json()["enabled"] is False
    login(client, account.email, PASSWORD)  # снова без кода
