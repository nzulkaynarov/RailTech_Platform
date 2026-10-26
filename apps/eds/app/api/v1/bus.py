"""«Журнал интеграций» шины rt_bus (`/api/v1/bus/*`, eds.yaml, тег `bus`; W13-A2) — то, что раньше было только в CLI
`python -m app bus status|dead|failed|retry|retry-dead|retry-inbox`.

Право — `bus.manage` (раздел `admin` каталога Платформы, уровень `full`). Логика — библиотечная (`rt_bus`, общая с CRM и
ERP); повтор идемпотентен (нечего повторять — `retried: 0`) и пишется в журнал EDS (кто, когда) и в лог шины (`actor`).
Тел событий API не отдаёт — только метаданные доставки.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_bus, get_session, require_permission
from app.models import Employee
from app.schemas.bus import (
    SUBSCRIBER_PATTERN,
    BusDelivery,
    BusDeliveryPage,
    BusInboxEntry,
    BusInboxPage,
    BusOverview,
    BusRetryDeadIn,
    BusRetryResult,
    DeliveryStatus,
    InboxStatus,
)
from app.schemas.pagination import Limit
from app.security.permissions import EdsPermission as P
from app.services import journal

router = APIRouter(prefix="/api/v1/bus", tags=["bus"])

Manager = Annotated[Employee, Depends(require_permission(P.BUS_MANAGE))]
Bus = Annotated[AsyncBus, Depends(get_bus)]
Session = Annotated[AsyncSession, Depends(get_session)]
TypeQuery = Annotated[str | None, Query(min_length=1, max_length=200)]


def _actor(employee: Employee) -> str:
    return f"crm-user:{employee.crm_user_id}"


async def _journal(session: AsyncSession, action: str, employee: Employee, comment: str) -> None:
    async with session.begin():
        await journal.record(session, action, by=employee.crm_user_id, comment=comment)


@router.get("/overview", response_model=BusOverview, operation_id="busOverview")
async def overview(_: Manager, bus: Bus) -> BusOverview:
    return BusOverview.model_validate(await bus.overview())


@router.get("/deliveries", response_model=BusDeliveryPage, operation_id="busDeliveries")
async def deliveries(
    _: Manager,
    bus: Bus,
    status: DeliveryStatus | None = None,
    subscriber: Annotated[str | None, Query(pattern=SUBSCRIBER_PATTERN)] = None,
    type: TypeQuery = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Limit = 50,
) -> BusDeliveryPage:
    rows = await bus.list_deliveries(
        status=status,
        subscriber=subscriber,
        type_contains=type,
        created_from=created_from,
        created_to=created_to,
        before_id=before_id,
        limit=limit + 1,
    )
    return BusDeliveryPage(items=[BusDelivery.model_validate(r) for r in rows[:limit]], has_more=len(rows) > limit)


@router.post("/deliveries/{delivery_id}/retry", response_model=BusRetryResult, operation_id="busRetryDelivery")
async def retry_delivery(
    delivery_id: Annotated[int, Path(ge=1)], employee: Manager, bus: Bus, session: Session
) -> BusRetryResult:
    done = int(await bus.retry_delivery(delivery_id, actor=_actor(employee)))
    await _journal(session, "bus.delivery_retried", employee, f"доставка {delivery_id}, поставлено: {done}")
    return BusRetryResult(retried=done)


@router.post("/deliveries/retry-dead", response_model=BusRetryResult, operation_id="busRetryDead")
async def retry_dead(body: BusRetryDeadIn, employee: Manager, bus: Bus, session: Session) -> BusRetryResult:
    count = await bus.retry_all_dead(body.subscriber, actor=_actor(employee))
    await _journal(session, "bus.dead_retried", employee, f"подписчик {body.subscriber}, поставлено: {count}")
    return BusRetryResult(retried=count)


@router.get("/inbox", response_model=BusInboxPage, operation_id="busInbox")
async def inbox(
    _: Manager,
    bus: Bus,
    errors: bool = False,
    status: InboxStatus | None = None,
    type: TypeQuery = None,
    before: datetime | None = None,
    before_event_id: uuid.UUID | None = None,
    limit: Limit = 50,
) -> BusInboxPage:
    rows = await bus.list_inbox(
        status=status,
        type_contains=type,
        errors_only=errors,
        before=before,
        before_event_id=before_event_id,
        limit=limit + 1,
    )
    return BusInboxPage(items=[BusInboxEntry.model_validate(r) for r in rows[:limit]], has_more=len(rows) > limit)


@router.post("/inbox/{event_id}/retry", response_model=BusRetryResult, operation_id="busRetryInbox")
async def retry_inbox(event_id: uuid.UUID, employee: Manager, bus: Bus, session: Session) -> BusRetryResult:
    done = int(await bus.retry_inbox(event_id, actor=_actor(employee)))
    await _journal(session, "bus.inbox_retried", employee, f"событие {event_id}, поставлено: {done}")
    return BusRetryResult(retried=done)
