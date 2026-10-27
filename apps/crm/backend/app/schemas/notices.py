"""Итог сообщений клиенту и приглашения в кабинет в карточках лида и клиента (D1-9).

`status`: `queued` (в очереди или письмо ещё идёт), `sent`, `failed`, `skipped` (слать
некуда/нечем). `error` — код
причины, `error_text` — те же слова для менеджера (`domain/notice_errors.py`). Для приглашения
добавляются каналы:
что можно выбрать для «Отправить повторно другим каналом» и какой канал разумно предложить.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NoticeStatus = Literal["queued", "sent", "failed", "skipped"]
NoticeChannel = Literal["telegram", "email", "both", "none"]
InviteChannel = Literal["email", "telegram", "both"]


class NoticeOut(BaseModel):
    id: int
    channel: NoticeChannel
    status: NoticeStatus
    error: str | None = None
    error_text: str | None = None
    created_at: datetime
    sent_at: datetime | None = None


class InvitationOut(NoticeOut):
    """Приглашение клиента в кабинет: последняя попытка и что можно сделать дальше."""

    contact_id: int | None = None
    contact_name: str | None = None
    # Каналы, по которым приглашение реально ушло или передано боту (`telegram` — итог доставки в
    # `status`).
    sent_via: list[Literal["email", "telegram"]] = Field(default_factory=list)
    # Каналы, доступные у контакта сейчас: есть e-mail / Telegram, который знает бот.
    available_channels: list[Literal["email", "telegram"]] = Field(default_factory=list)
    # Канал для «Отправить повторно другим каналом»: отличный от неудачного, если он доступен.
    suggested_channel: InviteChannel | None = None
    # Клиент уже в ERP — иначе приглашать некуда (повторная отправка недоступна).
    can_resend: bool = False


class InviteRequest(BaseModel):
    channel: InviteChannel
    contact_id: int | None = None
