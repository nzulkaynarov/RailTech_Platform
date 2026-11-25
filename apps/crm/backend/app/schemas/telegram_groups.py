"""DTO групп Telegram с секретарём (ADR-0032). Кода привязки в ответах нет: он только в группе."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GroupLanguage = Literal["ru", "uz", "en"]
TopicMode = Literal["none", "request"]


class TelegramGroupOut(BaseModel):
    chat_id: int
    title: str
    chat_type: str
    # pending — ждёт код; bound — привязана и пишется; unbound — отключена; removed — бота убрали.
    status: Literal["pending", "bound", "unbound", "removed"]
    # admin_required — «нужны права администратора»: бот не читает всё или не может закрепить.
    access: Literal["ok", "admin_required"]
    client_id: int | None
    client_name: str | None
    # Якорный лид беседы группы: переписка — `GET /leads/{lead_id}/messages`, сообщения с
    # `channel = "group"`; null, пока группа не привязана.
    lead_id: int | None
    # Тема на заявку — настройка ТГ-2: хранится, бот пока ей не пользуется.
    topic_mode: TopicMode
    language: GroupLanguage | None
    # Код привязки выпущен и не просрочен (сам код — только в группе).
    code_active: bool
    bound_at: datetime | None
    detected_at: datetime


class TelegramGroupBindIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=4, max_length=16)
    client_id: int = Field(gt=0)
    language: GroupLanguage | None = None


class TelegramGroupSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_mode: TopicMode | None = None
    language: GroupLanguage | None = None
