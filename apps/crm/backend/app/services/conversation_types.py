"""Типы диалогового потока: входящее и исходящее сообщения, ход агента, хуки."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.language import Language

Keyboard = Literal["consent", "language", "erase_confirm", "handoff_offer"]
ActivityHook = Callable[[int], Awaitable[None]]
EscalationHook = Callable[[int, int], Awaitable[None]]
AttachmentsEraser = Callable[[list[str]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Incoming:
    tg_user_id: int
    chat_id: int
    text: str
    username: str | None = None
    first_name: str | None = None
    language_code: str | None = None
    message_id: int | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    human_requested: bool = False


@dataclass(frozen=True, slots=True)
class Outgoing:
    text: str
    keyboard: Keyboard | None = None
    message_id: int | None = None
    language: Language = "ru"
    lead_id: int | None = None
    document: dict[str, Any] | None = None
    # BOT-07: кнопки выбора документа (id из поиска кода, принадлежность проверяется при нажатии).
    choices: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class Turn:
    lead_id: int
    language: Language
    stage: str
    owner_mode: str
    text: str
    human: bool
    attachment: bool = False
    client_id: int | None = None

    @property
    def mode(self) -> Literal["prospect", "customer"]:
        return "customer" if self.client_id is not None else "prospect"
