"""DTO обращений сотрудников к администратору и уведомлений сотруднику (W15-H7)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.staff_tickets import Status, Subject


class TicketIn(BaseModel):
    """Обращение: тема из списка, текст; страница и роль подставляет Платформа. Значения проверяет
    домен (подкод в `details.reason`), здесь — только грубые пределы."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(max_length=32)
    body: str = Field(max_length=20000)
    page: str | None = Field(default=None, max_length=2000)
    role: str | None = Field(default=None, max_length=500)


class TicketReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=20000)
    status: Status | None = None


class TicketStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status


class TicketRowOut(BaseModel):
    id: int
    number: str
    subject: Subject
    status: Status
    author_id: int
    author_name: str
    author_role: str | None = None
    page: str | None = None
    preview: str
    replies: int
    created_at: datetime
    updated_at: datetime


class TicketMessageOut(BaseModel):
    id: int
    author_id: int | None = None
    author_name: str | None = None
    body: str
    created_at: datetime


class TicketOut(TicketRowOut):
    body: str
    messages: list[TicketMessageOut]
    resolved_at: datetime | None = None


class TicketCounts(BaseModel):
    new: int
    in_progress: int
    resolved: int


class TicketPageOut(BaseModel):
    items: list[TicketRowOut]
    total: int
    counts: TicketCounts


class StaffNotificationOut(BaseModel):
    id: int
    kind: str
    tab: str
    title: str
    subtitle: str | None = None
    object_kind: str | None = None
    object_id: str | None = None
    object_number: str | None = None
    created_at: datetime
    read: bool


class StaffNotificationsOut(BaseModel):
    items: list[StaffNotificationOut]
    unread_count: int
