"""Обращения сотрудников к администратору — схемы `Ticket*` контракта BFF (W15-H7).

Владелец данных — CRM (ADR-0015). BFF переводит ответы в словарь Платформы: номер `ОБР-0012`
вместо внутреннего id, имя автора, ответы админа; роль автора подставляет сам по сессии, не
доверяя браузеру.
"""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.session import SessionData

TicketSubject = Literal["access", "notification", "template", "error", "other"]
TicketStatus = Literal["new", "in_progress", "resolved"]

NUMBER_PATTERN = r"^ОБР-[0-9]{1,9}$"
_NUMBER = re.compile(r"^ОБР-([0-9]{1,9})$")


def ticket_id_of(number: str) -> int | None:
    """`ОБР-0012` -> 12 (идентификатор CRM); не номер обращения — `None`."""
    match = _NUMBER.match(number)
    return int(match.group(1)) if match else None


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: TicketSubject
    body: str = Field(min_length=1, max_length=20000)
    page: str | None = Field(default=None, max_length=2000)


class TicketReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=20000)
    status: TicketStatus | None = None


class TicketStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TicketStatus


class TicketAuthor(BaseModel):
    id: str
    name: str


class TicketRow(BaseModel):
    number: str = Field(pattern=NUMBER_PATTERN)
    subject: TicketSubject
    status: TicketStatus
    author: TicketAuthor
    author_role: str | None = None
    page: str | None = None
    preview: str
    replies: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class TicketMessage(BaseModel):
    author_name: str | None = None
    body: str
    created_at: datetime


class Ticket(TicketRow):
    body: str
    messages: list[TicketMessage]
    resolved_at: datetime | None = None


class TicketList(BaseModel):
    items: list[TicketRow]


class TicketCounts(BaseModel):
    new: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    resolved: int = Field(ge=0)


class TicketPage(BaseModel):
    items: list[TicketRow]
    total: int = Field(ge=0)
    counts: TicketCounts


def author_role_of(data: SessionData) -> str | None:
    """Роль автора на момент обращения: выбранная («вид»), иначе все роли через запятую."""
    chosen = [r.name for r in data.roles if r.id == data.active_role]
    names = chosen or [r.name for r in data.roles]
    return ", ".join(names) or None


def to_row(row: dict[str, Any]) -> TicketRow:
    return TicketRow(
        number=str(row["number"]),
        subject=row["subject"],
        status=row["status"],
        author=TicketAuthor(id=str(row["author_id"]), name=str(row["author_name"])),
        author_role=row.get("author_role") or None,
        page=row.get("page") or None,
        preview=str(row.get("preview") or ""),
        replies=int(row.get("replies") or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def to_ticket(row: dict[str, Any]) -> Ticket:
    base = to_row(row).model_dump()
    return Ticket(
        **base,
        body=str(row["body"]),
        messages=[
            TicketMessage(
                author_name=m.get("author_name") or None,
                body=str(m["body"]),
                created_at=m["created_at"],
            )
            for m in row.get("messages") or []
        ],
        resolved_at=row.get("resolved_at") or None,
    )
