"""Обращения сотрудников к администратору (tag `tickets`, W15-H7).

«Написать администратору» и раздел «Настройки · Обращения сотрудников». Решения и данные — в CRM
(ADR-0015), токеном самого сотрудника: автор видит только своё, список всех, ответ и статус — права
раздела `admin` (директор читает, администратор правит; проверяют и BFF, и CRM). BFF подставляет
роль автора из сессии, переводит номер `ОБР-0012` в id CRM, а ошибки — в формат `Error`.
"""

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Path, Query, status

from app.deps import Authed, require, require_any_section
from app.errors import PlatformError, backend_reason, from_backend
from app.schemas_tickets import (
    NUMBER_PATTERN,
    Ticket,
    TicketCreate,
    TicketList,
    TicketPage,
    TicketReply,
    TicketStatus,
    TicketStatusChange,
    TicketSubject,
    author_role_of,
    ticket_id_of,
    to_row,
    to_ticket,
)

router = APIRouter(tags=["tickets"])

CRM = "/api/v1/staff-tickets"
Author = Annotated[Authed, Depends(require_any_section)]
AdminRead = Annotated[Authed, Depends(require("admin", "read"))]
AdminWrite = Annotated[Authed, Depends(require("admin", "full"))]
Number = Annotated[str, Path(pattern=NUMBER_PATTERN, description="Номер обращения `ОБР-0012`")]

_MESSAGES = {
    "ticket_subject_unknown": "Выберите тему из списка.",
    "ticket_text_empty": "Опишите, что случилось.",
    "ticket_text_too_long": "Текст длиннее 4000 символов: сократите его.",
    "ticket_page_invalid": "Адрес страницы указан неверно: обновите страницу и повторите.",
    "ticket_reply_empty": "Напишите ответ.",
    "ticket_reply_too_long": "Ответ длиннее 4000 символов: сократите его.",
    "ticket_status_unknown": "Такого статуса нет.",
    "ticket_status_transition": "Так сменить статус нельзя: обновите страницу.",
}
_FIELDS = {"subject": "subject", "body": "body", "page": "page", "status": "status"}


def _translate(response: httpx.Response) -> PlatformError:
    """4xx CRM -> `Error`: ошибка значения — 422 с `details.fields` и `details.reason`."""
    reason = backend_reason(response)
    if response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT and reason in _MESSAGES:
        field = _field_of(response)
        return PlatformError(
            "VALIDATION_FAILED",
            _MESSAGES[reason],
            status_code=422,
            source="crm",
            details={"fields": [field] if field else [], "reason": reason},
        )
    if response.status_code == status.HTTP_409_CONFLICT and reason in _MESSAGES:
        return PlatformError(
            "CONFLICT",
            _MESSAGES[reason],
            status_code=409,
            source="crm",
            details={"reason": reason},
        )
    err = from_backend("crm", response)
    if reason and err.body.details is not None:
        err.body.details["reason"] = reason
    if (
        response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        and reason == "ticket_rate_limited"
    ):
        err.body.message = "Вы отправили слишком много обращений. Подождите немного и повторите."
    return err


def _field_of(response: httpx.Response) -> str | None:
    try:
        field = response.json()["details"]["field"]
    except (ValueError, KeyError, TypeError):
        return None
    return _FIELDS.get(field) if isinstance(field, str) else None


def _json(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        raise _translate(response)
    return response.json()


def _id(number: str) -> int:
    ticket_id = ticket_id_of(number)
    if ticket_id is None:  # путь уже проверен шаблоном; запасной путь на случай расхождения
        raise PlatformError("NOT_FOUND", "Не найдено.", status_code=404)
    return ticket_id


@router.post(
    "/tickets",
    response_model=Ticket,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="createTicket",
)
async def create_ticket(body: TicketCreate, authed: Author) -> Ticket:
    payload = {
        "subject": body.subject,
        "body": body.body,
        "page": body.page,
        "role": author_role_of(authed.data),
    }
    return to_ticket(_json(await authed.call("crm", "POST", CRM, json=payload)))


@router.get(
    "/tickets",
    response_model=TicketList,
    response_model_exclude_none=True,
    operation_id="listMyTickets",
)
async def list_my_tickets(authed: Author) -> TicketList:
    rows = _json(await authed.call("crm", "GET", f"{CRM}/mine"))
    return TicketList(items=[to_row(r) for r in rows])


@router.get(
    "/tickets/{number}",
    response_model=Ticket,
    response_model_exclude_none=True,
    operation_id="getMyTicket",
)
async def get_my_ticket(number: Number, authed: Author) -> Ticket:
    return to_ticket(_json(await authed.call("crm", "GET", f"{CRM}/mine/{_id(number)}")))


@router.get(
    "/admin/tickets",
    response_model=TicketPage,
    response_model_exclude_none=True,
    operation_id="listTickets",
)
async def list_tickets(
    authed: AdminRead,
    ticket_status: Annotated[TicketStatus | None, Query(alias="status")] = None,
    subject: TicketSubject | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> TicketPage:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if ticket_status is not None:
        params["status"] = ticket_status
    if subject is not None:
        params["subject"] = subject
    body = _json(await authed.call("crm", "GET", CRM, params=params))
    return TicketPage(
        items=[to_row(r) for r in body["items"]], total=body["total"], counts=body["counts"]
    )


@router.get(
    "/admin/tickets/{number}",
    response_model=Ticket,
    response_model_exclude_none=True,
    operation_id="getTicket",
)
async def get_ticket(number: Number, authed: AdminRead) -> Ticket:
    return to_ticket(_json(await authed.call("crm", "GET", f"{CRM}/{_id(number)}")))


@router.post(
    "/admin/tickets/{number}/reply",
    response_model=Ticket,
    response_model_exclude_none=True,
    operation_id="replyTicket",
)
async def reply_ticket(number: Number, body: TicketReply, authed: AdminWrite) -> Ticket:
    payload = body.model_dump(exclude_none=True)
    return to_ticket(
        _json(await authed.call("crm", "POST", f"{CRM}/{_id(number)}/reply", json=payload))
    )


@router.post(
    "/admin/tickets/{number}/status",
    response_model=Ticket,
    response_model_exclude_none=True,
    operation_id="setTicketStatus",
)
async def set_ticket_status(number: Number, body: TicketStatusChange, authed: AdminWrite) -> Ticket:
    return to_ticket(
        _json(
            await authed.call(
                "crm", "POST", f"{CRM}/{_id(number)}/status", json={"status": body.status}
            )
        )
    )
