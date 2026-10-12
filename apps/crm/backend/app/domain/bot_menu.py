"""Интерфейс клиентского бота по статусу собеседника (Q-011, Q-020). Чистые функции.

Код решает, какое меню видит человек и когда спросить номер: модель в этом не участвует
(CLAUDE.md §1.3). Клиент — только подтверждённая менеджером привязка Telegram к активному
клиенту (`verified_client`), тот же признак, что включает режим customer у агента.
"""

import re
from typing import Final, Literal

from app.domain.stages import OwnerMode, Stage

MenuVariant = Literal["prospect", "with_manager", "client"]
Command = Literal["start", "human", "lang", "help", "delete", "docs", "request", "status"]

MENUS: Final[dict[MenuVariant, tuple[Command, ...]]] = {
    "prospect": ("start", "human", "lang", "help", "delete"),
    # Менеджер уже ведёт диалог — «Связаться с менеджером» не нужна.
    "with_manager": ("start", "lang", "help", "delete"),
    "client": ("docs", "request", "status", "lang", "delete"),
}
CLIENT_COMMANDS: Final[frozenset[Command]] = frozenset({"docs", "request", "status"})

# Лид «квалифицирован» или уже передан менеджеру — момент спросить номер (Q-020).
_PHONE_STAGES: Final[frozenset[str]] = frozenset(
    {Stage.QUALIFIED, Stage.HANDOFF, Stage.IN_PROGRESS}
)
_E164: Final = re.compile(r"^[1-9]\d{7,14}$")


def menu_variant(*, is_client: bool, owner_mode: str | None) -> MenuVariant:
    if is_client:
        return "client"
    if owner_mode == OwnerMode.HUMAN:
        return "with_manager"
    return "prospect"


def should_ask_phone(
    *,
    enabled: bool,
    already_asked: bool,
    has_phone: bool,
    is_client: bool,
    stage: str | None,
    owner_mode: str | None,
) -> bool:
    """Один раз за жизнь лида: квалифицирован или просил менеджера, номера ещё нет."""
    if not enabled or already_asked or has_phone or is_client or stage is None:
        return False
    return stage in _PHONE_STAGES or owner_mode in (OwnerMode.HUMAN, OwnerMode.PAUSED)


def normalize_phone(raw: str) -> str | None:
    """Номер из контакта Telegram → E.164 (`+998901234567`); мусор → None."""
    digits = re.sub(r"[\s()\-.]", "", raw.strip()).removeprefix("+")
    return f"+{digits}" if _E164.fullmatch(digits) else None
