"""Меню и запрос номера по статусу собеседника (Q-011, Q-020) — таблицы кейсов."""

import pytest

from app.domain.bot_menu import MENUS, menu_variant, normalize_phone, should_ask_phone


@pytest.mark.parametrize(
    ("is_client", "owner_mode", "variant"),
    [
        (False, None, "prospect"),  # ещё не писал
        (False, "bot", "prospect"),
        (False, "paused", "prospect"),  # ждёт менеджера — «связаться» ещё уместно
        (False, "human", "with_manager"),
        (True, "bot", "client"),
        (True, "human", "client"),  # клиенту меню клиента, даже если ведёт менеджер
    ],
)
def test_menu_variant(is_client: bool, owner_mode: str | None, variant: str) -> None:
    assert menu_variant(is_client=is_client, owner_mode=owner_mode) == variant


@pytest.mark.parametrize(
    ("variant", "commands"),
    [
        ("prospect", ("start", "human", "lang", "help", "delete")),
        ("with_manager", ("start", "lang", "help", "delete")),
        ("client", ("docs", "request", "status", "lang", "delete")),
    ],
)
def test_menu_commands(variant: str, commands: tuple[str, ...]) -> None:
    assert MENUS[variant] == commands  # type: ignore[index]


BASE = {
    "enabled": True,
    "already_asked": False,
    "has_phone": False,
    "is_client": False,
    "stage": "engaged",
    "owner_mode": "bot",
}


@pytest.mark.parametrize(
    ("change", "ask"),
    [
        ({}, False),  # просто разговор — не спрашиваем
        ({"stage": "qualified"}, True),
        ({"stage": "handoff"}, True),
        ({"owner_mode": "paused"}, True),  # попросил менеджера
        ({"owner_mode": "human"}, True),
        ({"stage": "qualified", "already_asked": True}, False),  # только один раз
        ({"stage": "qualified", "has_phone": True}, False),
        ({"stage": "qualified", "enabled": False}, False),  # bot.ask_phone = false
        ({"stage": "qualified", "is_client": True}, False),
        ({"stage": None}, False),  # нет лида
        ({"stage": "lost"}, False),
    ],
)
def test_should_ask_phone(change: dict[str, object], ask: bool) -> None:
    assert should_ask_phone(**{**BASE, **change}) is ask  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "e164"),
    [
        ("998901234567", "+998901234567"),  # Telegram часто присылает без «+»
        ("+998 (90) 123-45-67", "+998901234567"),
        ("+14155552671", "+14155552671"),
        ("12345", None),
        ("+0998901234567", None),
        ("phone", None),
        ("", None),
    ],
)
def test_normalize_phone(raw: str, e164: str | None) -> None:
    assert normalize_phone(raw) == e164
