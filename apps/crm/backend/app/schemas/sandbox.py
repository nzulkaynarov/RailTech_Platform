"""DTO «Проверить бота» — песочница диалога в CRM (аудит 2026-10-12 §3 п. 10)."""

from typing import Literal

from pydantic import BaseModel, Field

SandboxLanguage = Literal["ru", "uz", "en"]


class SandboxMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: SandboxLanguage = "ru"


class SandboxReply(BaseModel):
    text: str
    buttons: list[str]


class SandboxWhy(BaseModel):
    """Почему бот так ответил: решение, причина, документы базы знаний, сработавшие триггеры."""

    decision: str
    reason: str | None
    best_score: float | None
    documents: list[str]
    triggers: list[str]
    priority: str | None


class SandboxTurnOut(BaseModel):
    replies: list[SandboxReply]
    why: SandboxWhy
