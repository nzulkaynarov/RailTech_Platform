"""Webhook принимается только в режиме webhook и с верным secret_token."""

from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from fastapi.testclient import TestClient

from app.bot.process import create_bot_app
from app.bot.runtime import BotRuntime
from app.config import Settings
from app.main import create_app

TOKEN = "123456:TEST-token-for-unit-tests-only"


def runtime(mode: str, secret: str) -> BotRuntime:
    config = Settings(_env_file=None, telegram_mode=mode, telegram_webhook_secret=secret)
    return BotRuntime(config, Bot(TOKEN), Dispatcher())


@pytest.mark.parametrize(
    ("mode", "expected", "received", "ok"),
    [
        ("webhook", "s3cr3t-value", "s3cr3t-value", True),
        ("webhook", "s3cr3t-value", "wrong", False),
        ("webhook", "s3cr3t-value", None, False),
        ("webhook", "", "", False),
        ("polling", "s3cr3t-value", "s3cr3t-value", False),
    ],
)
def test_secret_matches(mode: str, expected: str, received: str | None, ok: bool) -> None:
    assert runtime(mode, expected).secret_matches(received) is ok


def test_api_does_not_serve_the_webhook() -> None:
    """S0-4: вебхук принимает `crm-bot`; в `crm-api` маршрута нет, даже при верном секрете."""
    app = create_app(Settings(_env_file=None, app_env="test", telegram_mode="webhook"))
    with TestClient(app) as client:
        assert not hasattr(app.state, "bot")
        response = client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "anything"},
        )
    assert response.status_code == 404


def test_webhook_is_hidden_when_bot_disabled() -> None:
    app = create_bot_app(Settings(_env_file=None, app_env="test", telegram_mode="disabled"))
    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "anything"},
        )
    assert response.status_code == 404


def test_webhook_feeds_update_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_bot_app(Settings(_env_file=None, app_env="test", telegram_mode="disabled"))
    fed: list[dict[str, Any]] = []
    rt = runtime("webhook", "s3cr3t-value")
    monkeypatch.setattr(rt, "feed", fed.append)
    with TestClient(app) as client:
        app.state.bot = rt
        response = client.post(
            "/telegram/webhook",
            json={"update_id": 42},
            headers={"X-Telegram-Bot-Api-Secret-Token": "s3cr3t-value"},
        )
    assert response.status_code == 200
    assert fed == [{"update_id": 42}]


# --- FIX-66: пустой или не-https адрес вебхука не запускает бота и не удаляет вебхук -------------


class RecordingBot:
    """Подставной Bot: фиксирует вызовы, которые меняют вебхук на стороне Telegram."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.session = type("S", (), {"close": staticmethod(lambda: None)})()

    async def set_webhook(self, url: str, **kwargs: Any) -> None:
        self.calls.append(f"set_webhook:{url}")

    async def delete_webhook(self, **kwargs: Any) -> None:
        self.calls.append("delete_webhook")

    async def set_my_commands(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append("set_my_commands")

    def __getattr__(self, name: str) -> Any:
        async def call(*args: Any, **kwargs: Any) -> None:
            self.calls.append(name)

        return call


@pytest.mark.parametrize(
    "url", ["", "   ", "http://crm.example/telegram/webhook", "crm.example/telegram/webhook"]
)
async def test_webhook_mode_with_bad_url_never_calls_set_webhook(url: str) -> None:
    """Сторож: `set_webhook` с пустым или не-https адресом не вызывается никогда (FIX-66)."""
    from app.bot.runtime import WebhookNotConfiguredError

    config = Settings(
        _env_file=None,
        telegram_mode="webhook",
        telegram_webhook_url=url,
        telegram_webhook_secret="s3cr3t-value",
    )
    bot = RecordingBot()
    rt = BotRuntime(config, bot, Dispatcher())  # type: ignore[arg-type]
    with pytest.raises(WebhookNotConfiguredError):
        await rt.start()
    assert not any(c.startswith(("set_webhook", "delete_webhook")) for c in bot.calls)
    assert bot.calls == []


async def test_webhook_url_is_stripped_before_set_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.bot import commands
    from app.bot import runtime as module

    async def nothing(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(commands, "publish", nothing)
    monkeypatch.setattr(module, "publish_profile", nothing)
    config = Settings(
        _env_file=None,
        telegram_mode="webhook",
        telegram_webhook_url="  https://crm.example/telegram/webhook\n",
        telegram_webhook_secret="s3cr3t-value",
    )
    bot = RecordingBot()
    await BotRuntime(config, bot, Dispatcher()).start()  # type: ignore[arg-type]
    assert bot.calls == ["set_webhook:https://crm.example/telegram/webhook"]


async def test_webhook_mode_with_https_url_sets_it_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.bot import commands
    from app.bot import runtime as module

    async def nothing(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(commands, "publish", nothing)
    monkeypatch.setattr(module, "publish_profile", nothing)
    config = Settings(
        _env_file=None,
        telegram_mode="webhook",
        telegram_webhook_url="https://crm.example/telegram/webhook",
        telegram_webhook_secret="s3cr3t-value",
    )
    bot = RecordingBot()
    rt = BotRuntime(config, bot, Dispatcher())  # type: ignore[arg-type]
    await rt.start()
    assert bot.calls == ["set_webhook:https://crm.example/telegram/webhook"]
