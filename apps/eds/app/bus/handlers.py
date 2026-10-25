"""Обработчики входящих событий (подписки EDS — `packages/contracts/bus/subscriptions.yaml`, строка `eds`).

Обработчик выполняется задачей очереди в одной транзакции со статусом записи inbox (`rt_bus.process_inbox`):
исключение откатывает изменения и ставит автоповтор. Повтор события ничего не меняет — ключ inbox `event id`
и правило «более старый снимок не применяется».

Типы без обработчика (`erp.request.created`, `erp.quote.ready_for_approval` — домен, задача E3) приёмник
записывает как `skipped` и отвечает 200.
"""

import uuid

import structlog
from rt_bus import Event, HandlerRegistry
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.snapshots import UserDeactivated, UserEnvelope, parse_time
from app.services import employees

log = structlog.get_logger(__name__)

USER_CREATED = "uz.railtech.identity.user.created.v1"
USER_UPDATED = "uz.railtech.identity.user.updated.v1"
USER_DEACTIVATED = "uz.railtech.identity.user.deactivated.v1"


async def on_user_snapshot(event: Event, session: AsyncSession) -> None:
    snapshot = UserEnvelope.model_validate(event.data).user
    applied = await employees.apply_snapshot(session, snapshot, event_id=uuid.UUID(event.id))
    log.info(
        "employee_projection",
        crm_user_id=snapshot.crm_user_id,
        event_type=event.type,
        applied=applied,
    )


async def on_user_deactivated(event: Event, session: AsyncSession) -> None:
    data = UserDeactivated.model_validate(event.data)
    applied = await employees.apply_deactivation(
        session, data.crm_user_id, at=parse_time(event.time), event_id=uuid.UUID(event.id)
    )
    log.info(
        "employee_projection",
        crm_user_id=data.crm_user_id,
        event_type=event.type,
        applied=applied,
    )


def build_registry() -> HandlerRegistry:
    """Реестр обработчиков EDS; свой, а не общий `default_registry` — тесты и процессы не делят состояние."""
    registry = HandlerRegistry()
    registry.add(USER_CREATED, on_user_snapshot)
    registry.add(USER_UPDATED, on_user_snapshot)
    registry.add(USER_DEACTIVATED, on_user_deactivated)
    return registry
