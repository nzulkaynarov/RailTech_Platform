"""Webhook принимается только в режиме webhook и с верным secret_token."""

from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from fastapi.testclient import TestClient

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


def test_webhook_is_hidden_when_bot_disabled() -> None:
    app = create_app(Settings(_env_file=None, app_env="test", telegram_mode="disabled"))
    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "anything"},
        )
    assert response.status_code == 404


def test_webhook_feeds_update_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(Settings(_env_file=None, app_env="test", telegram_mode="disabled"))
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
