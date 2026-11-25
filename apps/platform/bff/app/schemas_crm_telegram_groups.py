"""Модели «Группы с клиентами» (ТГ-1б, ADR-0032): список групп Telegram с секретарём, привязка
кодом к клиенту, отключение и группа клиента для его карточки. Кода привязки здесь нет."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Состояние считает BFF из `status`, `access` и `code_active` CRM: экран не склеивает их сам.
GroupState = Literal[
    "waiting_code", "code_expired", "connected", "needs_admin", "disconnected", "removed"
]


class TelegramGroup(BaseModel):
    chat_id: int
    title: str
    state: GroupState
    client_id: int | None
    client_name: str | None
    # Номер якорного лида беседы группы `L-NNNN` — по нему открывается лента; не привязана — `None`
    lead: str | None
    bound_at: datetime | None
    detected_at: datetime


class TelegramGroupList(BaseModel):
    items: list[TelegramGroup]


class TelegramGroupBindIn(BaseModel):
    code: str = Field(min_length=4, max_length=16)
    client_id: int = Field(gt=0)


class ClientTelegramGroup(BaseModel):
    """Привязанная группа клиента; `None` — группы нет, раздел в карточке не показывается."""

    group: TelegramGroup | None
