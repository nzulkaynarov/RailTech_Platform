"""DTO мастера первого запуска, чек-листа настройки и бэкапов (scope-аудит §3 п. 7, 9; §4)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ChecklistKey = Literal[
    "company",
    "business_hours",
    "models",
    "bot",
    "channel",
    "kb",
    "team",
    "test_dialog",
]


class SetupState(BaseModel):
    needs_setup: bool


class SetupAdminRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class ChecklistItem(BaseModel):
    key: ChecklistKey
    done: bool
    link: str


class SetupChecklist(BaseModel):
    items: list[ChecklistItem]
    done: int
    total: int


class BackupItem(BaseModel):
    name: str
    at: datetime
    size_bytes: int


class BackupsOut(BaseModel):
    available: bool = Field(description="Том бэкапов смонтирован в api")
    last_success_at: datetime | None
    stale: bool = Field(description="Последний успешный бэкап старше 26 ч или его нет")
    requested_at: datetime | None = Field(description="«Сделать сейчас» ждёт контейнер backup")
    items: list[BackupItem]
