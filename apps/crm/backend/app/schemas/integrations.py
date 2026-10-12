"""DTO «Подключений»: статус бота без значения токена, смена токена с паролем, каналы."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class TelegramStatusOut(BaseModel):
    """Значение токена сюда не попадает никогда — только `configured` и `last4`."""

    configured: bool
    source: Literal["db", "env", "none"]
    last4: str | None
    updated_at: datetime | None
    username: str | None
    mode: str
    running: bool
    last_error: str | None
    secrets_enabled: bool
    channel_id: int | None
    channel_title: str | None


class TelegramTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(min_length=20, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=256)


class ChatCandidateOut(BaseModel):
    chat_id: int
    title: str
    chat_type: str
    detected_at: datetime
