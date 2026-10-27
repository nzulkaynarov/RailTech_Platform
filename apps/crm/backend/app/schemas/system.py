"""Схемы экрана «Состояние системы» (аудит 2026-10-12 §3 п. 6)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ComponentStatusOut(BaseModel):
    key: str
    title: str
    status: Literal["ok", "warn", "fail", "unknown"]
    reason: str
    checked_at: datetime | None
    expected_on_stand: bool = Field(
        default=False,
        description="Тестовый стенд: здесь это ожидаемо (секреты сервера, адрес CRM, бот)",
    )


class SystemStatusOut(BaseModel):
    status: Literal["ok", "warn", "fail", "unknown"]
    checked_at: datetime
    components: list[ComponentStatusOut]
