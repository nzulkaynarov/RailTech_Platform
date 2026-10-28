"""Обработчики входящих событий (подписки EDS — `packages/contracts/bus/subscriptions.yaml`, строка `eds`).

Обработчик выполняется задачей очереди в одной транзакции со статусом записи inbox (`rt_bus.process_inbox`):
исключение откатывает изменения и ставит автоповтор. Повтор события ничего не меняет — ключ inbox `event id`
и правило «более старый снимок не применяется».

Документы проектов (D2-5): `erp.contract.status_changed`, `erp.invoice.*`, `erp.act.*` → проекция реестра
`project_documents` (без публикации событий, идемпотентно, более старое событие не перезаписывает новое).

Домен (E3): `erp.request.created` → входящее письмо по заявке (идемпотентно по `erp_request_id`);
`erp.quote.ready_for_approval` → маршрут согласования КП (идемпотентно по КП и версии). Обработчики публикуют события
EDS через шину процесса в той же транзакции, что и изменение.
"""

import uuid
from collections.abc import Callable

import structlog
from rt_bus import Event, HandlerRegistry
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.erp_snapshots import ProjectDocumentEvent, QuoteReady, RequestCreated
from app.bus.snapshots import UserDeactivated, UserEnvelope, parse_time
from app.services import employees, letters, project_documents, quotes

log = structlog.get_logger(__name__)

USER_CREATED = "uz.railtech.identity.user.created.v1"
USER_UPDATED = "uz.railtech.identity.user.updated.v1"
USER_DEACTIVATED = "uz.railtech.identity.user.deactivated.v1"
REQUEST_CREATED = "uz.railtech.erp.request.created.v1"
QUOTE_READY = "uz.railtech.erp.quote.ready_for_approval.v1"


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


async def on_project_document(event: Event, session: AsyncSession) -> None:
    data = ProjectDocumentEvent.model_validate(event.data)
    row = await project_documents.apply(session, event.type, data, moment=parse_time(event.time))
    log.info(
        "project_document",
        event_type=event.type,
        number=row.number if row else None,
        applied=row is not None,
        event_id=event.id,
    )


def build_registry(get_bus: Callable[[], AsyncBus] | None = None) -> HandlerRegistry:
    """Реестр обработчиков EDS; свой, а не общий `default_registry` — тесты и процессы не делят состояние.

    `get_bus` отдаёт шину процесса для обработчиков, публикующих события; без неё регистрируется только проекция
    сотрудников.
    """
    registry = HandlerRegistry()
    registry.add(USER_CREATED, on_user_snapshot)
    registry.add(USER_UPDATED, on_user_snapshot)
    registry.add(USER_DEACTIVATED, on_user_deactivated)
    for event_type in project_documents.EVENT_STATUS:
        registry.add(event_type, on_project_document)
    if get_bus is not None:

        async def request_created(event: Event, session: AsyncSession) -> None:
            data = RequestCreated.model_validate(event.data)
            payload = data.payload
            letter = await letters.register_from_request(
                session,
                get_bus(),
                moment=parse_time(event.time),
                erp_company_id=data.erp_company_id,
                crm_client_id=data.crm_client_id,
                erp_deal_id=data.deal.erp_deal_id,
                deal_number=data.deal.number,
                title=data.deal.title,
                erp_request_id=payload.erp_request_id,
                summary=payload.summary,
                parties=letters.RequestParties(
                    company_name=payload.company_name,
                    company_inn=payload.company_inn,
                    contact_name=payload.contact_name,
                    manager_crm_user_id=payload.manager_crm_user_id,
                ),
                urgent=payload.urgency == "urgent",
                letter_file_id=payload.letter_file_id,
            )
            log.info("letter_for_request", number=letter.number, event_id=event.id)

        async def quote_ready(event: Event, session: AsyncSession) -> None:
            route = await quotes.open_for_quote(session, get_bus(), QuoteReady.model_validate(event.data))
            log.info("quote_route", route=str(route.id) if route else None, event_id=event.id)

        registry.add(REQUEST_CREATED, request_created)
        registry.add(QUOTE_READY, quote_ready)
    return registry
