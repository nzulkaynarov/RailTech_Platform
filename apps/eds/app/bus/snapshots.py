"""Снимок сотрудника из событий `uz.railtech.identity.user.*.v1` — терпимое чтение (L10).

Модели `rt_contracts` не используются намеренно: поле `user.permissions.eds` аддитивное и необязательное
(волна 12, E1), а читатель обязан работать и со старым CRM (поля нет), и с новым (есть, возможны новые коды).
Лишние поля игнорируются; неверный тип или нет обязательного поля — ошибка обработчика (автоповтор, затем `failed`).
"""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Permissions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    eds: list[str] = Field(default_factory=list)


class UserSnapshot(BaseModel):
    """`data.user` событий `user.created` и `user.updated`."""

    model_config = ConfigDict(extra="ignore")

    crm_user_id: int
    email: str
    full_name: str
    position: str | None = None
    language: Literal["ru", "uz", "en"] = "ru"
    is_active: bool
    permissions: Permissions | None = None
    updated_at: AwareDatetime

    @property
    def permissions_eds(self) -> list[str]:
        """Права EDS по снимку; поля нет (CRM без `permissions.eds`) — доступа нет."""
        return sorted(set(self.permissions.eds)) if self.permissions is not None else []


class UserEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user: UserSnapshot


class UserDeactivated(BaseModel):
    """`data` события `user.deactivated`."""

    model_config = ConfigDict(extra="ignore")

    crm_user_id: int


def parse_time(value: str) -> datetime:
    """Время конверта (RFC 3339, `Z`) → aware datetime."""
    return datetime.fromisoformat(value)
