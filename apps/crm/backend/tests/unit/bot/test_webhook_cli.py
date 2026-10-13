from unittest.mock import MagicMock

from app.bot.runtime import build_dispatcher
from app.cli.webhook import ALLOWED_UPDATES


def test_cli_allowed_updates_match_dispatcher() -> None:
    stub = MagicMock()
    dispatcher = build_dispatcher(stub, stub, stub, stub, "tg-attachments")
    assert sorted(dispatcher.resolve_used_update_types()) == sorted(ALLOWED_UPDATES)
