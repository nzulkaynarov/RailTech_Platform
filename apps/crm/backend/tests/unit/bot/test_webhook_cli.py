import argparse
from unittest.mock import MagicMock

import pytest

from app.bot.runtime import build_dispatcher
from app.cli.webhook import ALLOWED_UPDATES
from app.config import Settings


def test_cli_allowed_updates_match_dispatcher() -> None:
    stub = MagicMock()
    dispatcher = build_dispatcher(stub, stub, stub, stub, "tg-attachments")
    assert sorted(dispatcher.resolve_used_update_types()) == sorted(ALLOWED_UPDATES)


@pytest.mark.parametrize("url", ["", "http://crm.example/telegram/webhook"])
async def test_cli_set_refuses_empty_or_non_https_url(
    url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """FIX-66: `set` не зовёт Bot API с пустым адресом (это удаление вебхука) и не-https."""
    from app.cli import webhook as cli

    calls: list[str] = []

    async def close() -> None: ...

    class FakeBot:
        session = type("S", (), {"close": staticmethod(close)})()

        def __init__(self, token: str) -> None: ...

        async def set_webhook(self, *a: object, **k: object) -> None:
            calls.append("set_webhook")

        async def get_webhook_info(self) -> object:
            calls.append("get_webhook_info")
            return None

    class FakeContainer:
        secrets_store = None

        async def aclose(self) -> None: ...

    async def token(*a: object) -> tuple[str, str]:
        return "111:fake-cli-token", "env"

    monkeypatch.setattr(cli, "Bot", FakeBot)
    monkeypatch.setattr(cli, "get_container", lambda: FakeContainer())
    monkeypatch.setattr(cli, "resolve_token", token)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            telegram_webhook_url=url,
            telegram_webhook_secret="s3cr3t-value",
        ),
    )
    assert await cli.run(argparse.Namespace(action="set")) == 1
    assert calls == []
    assert "111:fake-cli-token" not in capsys.readouterr().out
