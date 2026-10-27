"""«Журнал интеграций» шины rt_bus в Admin Платформы (W13-A2): то, что раньше было только в CLI
`python -m app bus status|dead|failed|retry|retry-dead|retry-inbox` (`docs/runbooks/rt-bus-crm.md`).

Чтение — `integrations:read`, повторы — `integrations:write` (раздел `admin` каталога Платформы,
уровень `full`). Логика — библиотечная (`rt_bus`, общая с EDS и ERP); повтор идемпотентен (второй
раз — `retried: 0`) и пишется в журнал аудита (кто, когда) и в лог шины (`actor`). Тел событий API
не отдаёт — только метаданные доставки.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import ContainerDep, require
from app.schemas.bus import (
    SUBSCRIBER_PATTERN,
    BusDeliveryOut,
    BusDeliveryPageOut,
    BusInboxEntryOut,
    BusInboxPageOut,
    BusOverviewOut,
    BusRetryDeadIn,
    BusRetryOut,
    DeliveryStatus,
    InboxStatus,
)
from app.security import audit
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1/bus", tags=["bus"])

Reader = Annotated[Principal, Depends(require("integrations", "read"))]
Writer = Annotated[Principal, Depends(require("integrations", "write"))]
Limit = Annotated[int, Query(ge=1, le=100)]


def _actor(principal: Principal) -> str:
    return f"crm-user:{principal.user_id}"


async def _audit(
    container: ContainerDep,
    principal: Principal,
    action: str,
    entity_type: str,
    entity_id: object,
    retried: int,
) -> None:
    async with container.session_factory() as session, session.begin():
        await audit.record(
            session, principal.actor, action, entity_type, entity_id, after={"retried": retried}
        )


@router.get("/overview", response_model=BusOverviewOut, operation_id="busOverview")
async def overview(_: Reader, container: ContainerDep) -> BusOverviewOut:
    """Сводка шины CRM: outbox, DLQ, inbox и подписчики (очередь, предохранитель, выключен ли)."""
    return BusOverviewOut.model_validate(await container.bus.overview())


@router.get("/deliveries", response_model=BusDeliveryPageOut, operation_id="busDeliveries")
async def deliveries(
    _: Reader,
    container: ContainerDep,
    status: DeliveryStatus | None = None,
    subscriber: Annotated[str | None, Query(pattern=SUBSCRIBER_PATTERN)] = None,
    type: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Limit = 50,
) -> BusDeliveryPageOut:
    """Доставки событий CRM подписчикам, новые сверху; DLQ — `status=dead`.

    Страница — `before_id` (id последней строки предыдущей)."""
    rows = await container.bus.list_deliveries(
        status=status,
        subscriber=subscriber,
        type_contains=type,
        created_from=created_from,
        created_to=created_to,
        before_id=before_id,
        limit=limit + 1,
    )
    return BusDeliveryPageOut(
        items=[BusDeliveryOut.model_validate(r) for r in rows[:limit]], has_more=len(rows) > limit
    )


@router.post(
    "/deliveries/{delivery_id}/retry", response_model=BusRetryOut, operation_id="busRetryDelivery"
)
async def retry_delivery(
    delivery_id: Annotated[int, Path(ge=1)], principal: Writer, container: ContainerDep
) -> BusRetryOut:
    """«Повторить»: доставка `dead` или ожидающая — сейчас, попытки с нуля.

    Подписчик на паузе предохранителя сразу получает пробную доставку."""
    done = await container.bus.retry_delivery(delivery_id, actor=_actor(principal))
    await _audit(
        container, principal, "bus.delivery_retried", "bus_delivery", delivery_id, int(done)
    )
    return BusRetryOut(retried=int(done))


@router.post("/deliveries/retry-dead", response_model=BusRetryOut, operation_id="busRetryDead")
async def retry_dead(
    body: BusRetryDeadIn, principal: Writer, container: ContainerDep
) -> BusRetryOut:
    """«Повторить все dead подписчика» — после исправления причины (адрес, секрет, приёмник)."""
    count = await container.bus.retry_all_dead(body.subscriber, actor=_actor(principal))
    await _audit(container, principal, "bus.dead_retried", "bus_subscriber", body.subscriber, count)
    return BusRetryOut(retried=count)


@router.get("/inbox", response_model=BusInboxPageOut, operation_id="busInbox")
async def inbox(
    _: Reader,
    container: ContainerDep,
    errors: bool = False,
    status: InboxStatus | None = None,
    type: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    before: datetime | None = None,
    before_event_id: uuid.UUID | None = None,
    limit: Limit = 50,
) -> BusInboxPageOut:
    """Принятые события, новые сверху.

    `errors=true` — обработка упала (`failed`) или ждёт автоповтора. Страница — `before` и
    `before_event_id` последней строки предыдущей."""
    rows = await container.bus.list_inbox(
        status=status,
        type_contains=type,
        errors_only=errors,
        before=before,
        before_event_id=before_event_id,
        limit=limit + 1,
    )
    return BusInboxPageOut(
        items=[BusInboxEntryOut.model_validate(r) for r in rows[:limit]], has_more=len(rows) > limit
    )


@router.post("/inbox/{event_id}/retry", response_model=BusRetryOut, operation_id="busRetryInbox")
async def retry_inbox(
    event_id: uuid.UUID, principal: Writer, container: ContainerDep
) -> BusRetryOut:
    """«Повторить обработку» записи inbox `failed` или `skipped` (после исправления обработчика)."""
    done = await container.bus.retry_inbox(event_id, actor=_actor(principal))
    await _audit(container, principal, "bus.inbox_retried", "bus_inbox", event_id, int(done))
    return BusRetryOut(retried=int(done))
