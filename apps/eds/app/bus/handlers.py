"""Обработчики входящих событий (подписки EDS — `packages/contracts/bus/subscriptions.yaml`, строка `eds`).

Обработчик выполняется задачей очереди в одной транзакции со статусом записи inbox (`rt_bus.process_inbox`):
исключение откатывает изменения и ставит автоповтор. Повтор события ничего не меняет — ключ inbox `event id`
и правило «более старый снимок не применяется».

Документы проектов (D2-5): `erp.contract.status_changed`, `erp.invoice.*`, `erp.act.*` → проекция реестра
`project_documents` (без публикации событий, идемпотентно, более старое событие не перезаписывает новое).

Политика защиты данных для ИИ (PD-BIZ): `crm.ai_policy.changed` → проекция `docflow_settings.pii_policy`.

Домен (E3): `erp.request.created` → входящее письмо по заявке (идемпотентно по `erp_request_id`);
`erp.quote.ready_for_approval` → маршрут согласования КП (идемпотентно по КП и версии). Обработчики публикуют события
EDS через шину процесса в той же транзакции, что и изменение.
"""

import uuid
from collections.abc import Awaitable, Callable

import structlog
from rt_bus import Event, HandlerRegistry
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.erp_snapshots import ProjectDocumentEvent, QuoteReady, RequestCreated
from app.bus.snapshots import AiPolicyChanged, UserDeactivated, UserEnvelope, parse_time
from app.services import (
    docflow_settings,
    employees,
    letter_mail,
    letterhead,
    letters,
    project_documents,
    quotes,
)

log = structlog.get_logger(__name__)

USER_CREATED = "uz.railtech.identity.user.created.v1"
USER_UPDATED = "uz.railtech.identity.user.updated.v1"
USER_DEACTIVATED = "uz.railtech.identity.user.deactivated.v1"
REQUEST_CREATED = "uz.railtech.erp.request.created.v1"
QUOTE_READY = "uz.railtech.erp.quote.ready_for_approval.v1"
LETTERHEAD_UPDATED = "uz.railtech.erp.letterhead.updated.v1"
MAIL_SENT = "uz.railtech.crm.mail.sent.v1"
MAIL_FAILED = "uz.railtech.crm.mail.failed.v1"
AI_POLICY_CHANGED = "uz.railtech.crm.ai_policy.changed.v1"


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


async def on_letterhead(event: Event, session: AsyncSession) -> None:
    """Бланк своей компании из ERP (P4): проекция; более старый снимок не применяется."""
    data = letterhead.LetterheadUpdated.model_validate(event.data)
    applied = await letterhead.apply(session, data, moment=parse_time(event.time))
    log.info("letterhead_projection", erp_company_id=data.erp_company_id, applied=applied, event_id=event.id)


def mail_result_handler(get_bus: Callable[[], AsyncBus] | None) -> Callable[[Event, AsyncSession], Awaitable[None]]:
    """Итог письма адресату от почтового сервиса CRM (P4, B-W18AP1-1): строка журнала отправки; чужие итоги — мимо.
    «Не ушло» — ещё и уведомление автору и делопроизводителям (EDS-REPLY-1; шина процесса — через `get_bus`)."""

    async def on_mail_result(event: Event, session: AsyncSession) -> None:
        data = letter_mail.MailResult.model_validate(event.data)
        applied = await letter_mail.apply_result(
            session, data, sent=event.type == MAIL_SENT, bus=get_bus() if get_bus is not None else None
        )
        log.info("mail_result", event_type=event.type, request_key=data.request_key, applied=applied, event_id=event.id)

    return on_mail_result


async def on_ai_policy(event: Event, session: AsyncSession) -> None:
    """Политика защиты данных для ИИ из CRM (PD-BIZ): проекция; более старое событие не применяется."""
    data = AiPolicyChanged.model_validate(event.data)
    applied = await docflow_settings.apply_policy(
        session, data.pii_policy, changed_at=data.changed_at, actor_id=data.crm_user_id
    )
    log.info("ai_policy_projection", pii_policy=data.pii_policy, applied=applied, event_id=event.id)


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
    registry.add(LETTERHEAD_UPDATED, on_letterhead)
    on_mail_result = mail_result_handler(get_bus)
    registry.add(MAIL_SENT, on_mail_result)
    registry.add(MAIL_FAILED, on_mail_result)
    registry.add(AI_POLICY_CHANGED, on_ai_policy)
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
