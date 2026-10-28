"""Обращения сотрудников к администратору (W15-H7, ADR-0015): свои — любому, все — админу.

Автор видит и пишет только своё (`/me/tickets`); список всех, ответ и смена статуса — права
`tickets:read` / `tickets:write` раздела `admin` каталога (директор читает, администратор правит).
Чужое обращение автору отвечает 404: его не существует.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import ContainerDep, require
from app.api.v1.me import Settled
from app.schemas.staff_tickets import (
    TicketCounts,
    TicketIn,
    TicketMessageOut,
    TicketOut,
    TicketPageOut,
    TicketReplyIn,
    TicketRowOut,
    TicketStatusIn,
)
from app.security.principal import Principal
from app.services.staff_tickets import TicketDetail, TicketRow

router = APIRouter(prefix="/api/v1/staff-tickets", tags=["staff-tickets"])
# Свои обращения — отдельный префикс: `/mine/{id}` рядом с `/{id}/reply` читался бы двусмысленно.
mine_router = APIRouter(prefix="/api/v1/me/tickets", tags=["staff-tickets"])

Reader = Annotated[Principal, Depends(require("tickets", "read"))]
Writer = Annotated[Principal, Depends(require("tickets", "write"))]
TicketId = Annotated[int, Path(gt=0)]


def _slots(row: TicketRow) -> TicketRowOut:
    return TicketRowOut(
        id=row.id,
        number=row.number,
        subject=row.subject,
        status=row.status,
        author_id=row.author_id,
        author_name=row.author_name,
        author_role=row.author_role,
        page=row.page,
        preview=row.preview,
        replies=row.replies,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _detail(detail: TicketDetail) -> TicketOut:
    return TicketOut(
        **_slots(detail.row).model_dump(),
        body=detail.body,
        messages=[
            TicketMessageOut(
                id=m.id,
                author_id=m.author_id,
                author_name=m.author_name,
                body=m.body,
                created_at=m.created_at,
            )
            for m in detail.messages
        ],
        resolved_at=detail.resolved_at,
    )


@mine_router.post("", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
async def create_ticket(body: TicketIn, who: Settled, container: ContainerDep) -> TicketOut:
    """«Написать администратору»: не больше 5 обращений в час (429 `ticket_rate_limited`)."""
    detail = await container.staff_tickets.create(
        who.actor,
        who.user_id,
        subject=body.subject,
        body=body.body,
        page=body.page,
        role=body.role,
    )
    return _detail(detail)


@mine_router.get("", response_model=list[TicketRowOut])
async def list_my_tickets(who: Settled, container: ContainerDep) -> list[TicketRowOut]:
    return [_slots(r) for r in await container.staff_tickets.list_own(who.user_id)]


@mine_router.get("/{ticket_id}", response_model=TicketOut)
async def get_my_ticket(ticket_id: TicketId, who: Settled, container: ContainerDep) -> TicketOut:
    return _detail(await container.staff_tickets.get_own(who.user_id, ticket_id))


@router.get("", response_model=TicketPageOut)
async def list_tickets(
    _: Reader,
    container: ContainerDep,
    status_: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    subject: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
) -> TicketPageOut:
    page = await container.staff_tickets.list_all(
        status=status_, subject=subject, limit=limit, offset=offset
    )
    return TicketPageOut(
        items=[_slots(r) for r in page.items],
        total=page.total,
        counts=TicketCounts(**page.counts),
    )


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: TicketId, _: Reader, container: ContainerDep) -> TicketOut:
    return _detail(await container.staff_tickets.get(ticket_id))


@router.post("/{ticket_id}/reply", response_model=TicketOut)
async def reply_to_ticket(
    ticket_id: TicketId, body: TicketReplyIn, who: Writer, container: ContainerDep
) -> TicketOut:
    """Ответ автору (колокольчик и Telegram); новое обращение уходит «В работу»."""
    detail = await container.staff_tickets.reply(
        who.actor, ticket_id, body.body, status=body.status
    )
    return _detail(detail)


@router.post("/{ticket_id}/status", response_model=TicketOut)
async def set_ticket_status(
    ticket_id: TicketId, body: TicketStatusIn, who: Writer, container: ContainerDep
) -> TicketOut:
    return _detail(await container.staff_tickets.set_status(who.actor, ticket_id, body.status))
