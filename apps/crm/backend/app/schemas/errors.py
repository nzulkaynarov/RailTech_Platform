"""Тело ошибки API (`app/api/errors.py`) — в OpenAPI, чтобы фронт получил типы подкодов."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.errors import Reason


class ErrorDetails(BaseModel):
    """Подробности ошибки; кроме описанных полей бывают контекстные (`assigned_user_name`, …)."""

    model_config = ConfigDict(extra="allow")

    reason: Reason | None = Field(default=None, description="подкод конкретного случая")
    field: str | None = Field(default=None, description="поле формы, к которому относится ошибка")
    errors: list[dict[str, Any]] | None = Field(
        default=None, description="ошибки валидации запроса по полям"
    )


class ErrorOut(BaseModel):
    code: str = Field(description="класс ошибки: conflict, validation_failed, not_found, …")
    message: str = Field(description="для логов; пользователю — текст по code/details.reason")
    details: ErrorDetails
