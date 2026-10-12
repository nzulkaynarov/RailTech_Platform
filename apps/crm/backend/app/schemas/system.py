"""Схемы экрана «Состояние системы» (аудит 2026-10-12 §3 п. 6)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ComponentStatusOut(BaseModel):
    key: str
    title: str
    status: Literal["ok", "warn", "fail", "unknown"]
    reason: str
    checked_at: datetime | None


class SystemStatusOut(BaseModel):
    status: Literal["ok", "warn", "fail", "unknown"]
    checked_at: datetime
    components: list[ComponentStatusOut]
