"""Применение входящих событий ERP к зеркалу CRM (FIX-35): по классу конверта, payload типизирован.

`dispatch` получает конверт, разобранный дискриминированной моделью (`schemas/erp_events.py`),
меняет зеркало сделки и индекс документов клиента и возвращает текст заметки в ленту лида (если
она нужна). Тексты клиенту и сотруднику строит `services/erp_bot_messages.py` из
`settings.texts`; здесь их нет. Читатель терпимый: поле, которого модель не знает, сюда не
доходит.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.deals import DealStage, plan_erp_outcome
from app.models.clients import Client, ClientContact, Document
from app.models.deals import Deal
from app.schemas.erp_events import (
    ActEnvelope,
    ContractSignedEvent,
    DealOutcomeEvent,
    DealStageChangedEvent,
    DeliveryEnvelope,
    DeliveryLineEvent,
    DocumentCreatedEvent,
    ErpEventEnvelope,
    InviteSentEvent,
    InvoiceEnvelope,
    QuoteOutcomeEvent,
    QuoteSentEvent,
    RequestCreatedEvent,
)

DOC_KIND_MAP: dict[str, str] = {
    "quote": "proposal",
    "contract": "contract",
    "invoice": "invoice",
    "act": "act",
    "waybill": "other",
    "receipt": "other",
    "other": "other",
}


def aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def outcome_is_current(deal: Deal, occurred_at: datetime) -> bool:
    """Итог `won`/`lost` применяется, если сделка не закрыта более поздним итогом (по `closed_at`).

    Опоздавший итог НЕ теряется из-за более свежих событий другого типа (счёт, оплата): их порядок
    ведёт `external_stage_at`, а итог сделки упорядочен только относительно других итогов.
    """
    return deal.closed_at is None or aware(occurred_at) >= aware(deal.closed_at)


def _local_stage(deal: Deal) -> DealStage:
    return DealStage(deal.stage) if deal.stage in ("open", "won", "lost") else DealStage.OPEN


def _set_stage(deal: Deal | None, stage: str) -> None:
    if deal is not None:
        deal.external_stage = stage


def _request_created(env: RequestCreatedEvent) -> str:
    payload = env.payload
    return (
        f"В бэк-офисе создана заявка #{payload.erp_request_id or '—'} (источник: {payload.source})."
    )


def _stage_changed(env: DealStageChangedEvent, deal: Deal | None) -> str:
    payload = env.payload
    _set_stage(deal, payload.to)
    note = f"Стадия сделки в бэк-офисе: {payload.from_} → {payload.to}"
    return note + (f" ({payload.reason})" if payload.reason else "")


def _outcome(env: DealOutcomeEvent, deal: Deal | None, deal_title: str) -> str:
    payload = env.payload
    won = env.event == "deal.won"
    if deal is not None and outcome_is_current(deal, env.occurred_at):
        reason = None if won else payload.lost_reason
        plan = plan_erp_outcome(env.event, _local_stage(deal), reason)
        deal.stage = plan.stage.value
        deal.closed_at = env.occurred_at
        deal.external_stage = "won" if won else "lost"
        if won:
            deal.amount = Decimal(payload.amount)
            deal.currency = payload.currency
        else:
            deal.lost_reason = plan.lost_reason
    if won:
        return (
            f"Сделка «{deal_title}» успешно закрыта (won) "
            f"на сумму {payload.amount} {payload.currency}."
        )
    reason = payload.lost_reason or "не указана"
    return f"Сделка «{deal_title}» закрыта отказом (lost). Причина: {reason}."


def _quote_sent(env: QuoteSentEvent, deal: Deal | None) -> str:
    payload = env.payload
    _set_stage(deal, "quote_sent")
    parts = [f"Клиенту отправлено КП #{payload.erp_quote_id} v{payload.version}"]
    if payload.total and payload.currency:
        parts.append(f"на сумму {payload.total} {payload.currency}")
    if payload.public_url:
        parts.append(f"Ссылка: {payload.public_url}")
    return ". ".join(parts) + "."


def _quote_outcome(env: QuoteOutcomeEvent, deal: Deal | None, contact_name: str | None) -> str:
    """Запись ленты по КП; у принятия и отказа — кто из контактов клиента это сделал (шов 0.3.0)."""
    payload = env.payload
    label = f"#{payload.erp_quote_id} v{payload.version}"
    who = f" ({contact_name})" if contact_name else ""
    if env.event == "quote.viewed":
        return f"Клиент открыл КП {label}."
    if env.event == "quote.accepted":
        _set_stage(deal, "accepted")
        return f"Клиент{who} акцептовал КП {label}."
    reason = f". Причина: {payload.reason}." if payload.reason else "."
    return f"КП {label} отклонено клиентом{who}{reason}"


async def _crm_contact_name(
    session: AsyncSession, client: Client, crm_contact_id: int | None
) -> str | None:
    """Имя контакта CRM по `crm_contact_id` события; чужой или неизвестный контакт — `None`.

    Контакт обязан принадлежать клиенту события: идентификатор приходит из ERP, и подставлять
    в ленту имя контакта другого клиента нельзя.
    """
    if crm_contact_id is None:
        return None
    name = await session.scalar(
        select(ClientContact.full_name).where(
            ClientContact.id == crm_contact_id, ClientContact.client_id == client.id
        )
    )
    return name.strip() or None if name else None


def _contract_signed(env: ContractSignedEvent, deal: Deal | None) -> str:
    _set_stage(deal, "contract")
    return f"Договор {env.payload.number or ''} подписан ({env.payload.by})."


def _invoice(env: InvoiceEnvelope, deal: Deal | None) -> str:
    payload = env.payload
    if env.event == "invoice.issued":
        _set_stage(deal, "invoiced")
        return (
            f"Выставлен счёт {payload.number} на сумму {payload.amount} {payload.currency} "
            f"со сроком оплаты до {payload.due_date}."
        )
    if env.event == "invoice.paid":
        _set_stage(deal, "paid")
        return f"Счёт {payload.number} на сумму {payload.amount} {payload.currency} оплачен."
    return f"Счёт {payload.number} просрочен (срок оплаты был {payload.due_date})."


def _delivery(env: DeliveryEnvelope, deal: Deal | None) -> str:
    payload = env.payload
    if env.event == "delivery.status_changed":
        _set_stage(deal, "fulfilment")
        eta = f", ожидается {payload.eta}" if payload.eta else ""
        return f"Статус поставки ({payload.line_summary}): {payload.status}{eta}"
    return (
        f"Изменилась дата поставки ({payload.line_summary}): "
        f"{payload.previous_eta or '—'} → {payload.eta}."
    )


def _act(env: ActEnvelope, deal: Deal | None) -> str:
    payload = env.payload
    if env.event == "act.issued":
        _set_stage(deal, "closing")
        return f"Сформирован акт {payload.number}."
    if env.event == "act.accepted":
        return f"Акт {payload.number} принят клиентом."
    return f"Акт {payload.number} возвращён клиентом с замечаниями: {payload.reason or ''}."


async def _document_created(
    session: AsyncSession, env: DocumentCreatedEvent, client: Client
) -> str:
    """Индекс документов клиента: upsert по `(client_id, erp_document_id)`, дублей не плодит."""
    payload = env.payload
    title = payload.title or f"{payload.kind} {payload.number}"
    values = {
        "type": DOC_KIND_MAP.get(payload.kind, "other"),
        "title": title,
        "number": payload.number or None,
        "filename": f"{payload.kind}_{payload.number}.pdf",
    }
    existing = await _find_document(session, client.id, payload.erp_document_id)
    if existing is None:
        row = Document(
            client_id=client.id,
            erp_document_id=payload.erp_document_id,
            doc_date=env.occurred_at.date(),
            storage_key=None,
            mime="application/pdf",
            size_bytes=0,
            extract_status="skipped",
            is_visible_to_client=True,
            **values,
        )
        try:
            async with (
                session.begin_nested()
            ):  # параллельный выпуск того же документа: уникальный индекс
                session.add(row)
                await session.flush()
        except IntegrityError:
            existing = await _find_document(session, client.id, payload.erp_document_id)
            if existing is None:
                raise
    if existing is None:
        return f"В бэк-офисе создан документ: {title} ({payload.number})."
    for field, value in values.items():
        setattr(existing, field, value)
    return f"В бэк-офисе обновлён документ: {title} ({payload.number})."


async def _find_document(
    session: AsyncSession, client_id: int, erp_document_id: int
) -> Document | None:
    return await session.scalar(
        select(Document)
        .where(Document.client_id == client_id, Document.erp_document_id == erp_document_id)
        .with_for_update()
    )


def _invite_sent(env: InviteSentEvent) -> str:
    channels = ", ".join(env.payload.channels)
    return f"Контакту отправлено приглашение в кабинет через каналы: {channels}."


async def dispatch(
    session: AsyncSession, env: ErpEventEnvelope, client: Client, deal: Deal | None
) -> str | None:
    """Меняет зеркало сделки и индекс документов; возвращает текст заметки в ленту лида или
    `None`.
    """
    deal_title = env.deal.title if env.deal else (deal.title if deal else "Сделка")
    match env:
        case RequestCreatedEvent():
            return _request_created(env)
        case DealStageChangedEvent():
            return _stage_changed(env, deal)
        case DealOutcomeEvent():
            return _outcome(env, deal, deal_title)
        case QuoteSentEvent():
            return _quote_sent(env, deal)
        case QuoteOutcomeEvent():
            who = None
            if env.event != "quote.viewed":
                who = await _crm_contact_name(session, client, env.payload.crm_contact_id)
            return _quote_outcome(env, deal, who)
        case ContractSignedEvent():
            return _contract_signed(env, deal)
        case InvoiceEnvelope():
            return _invoice(env, deal)
        case DeliveryEnvelope():
            return _delivery(env, deal)
        case ActEnvelope():
            return _act(env, deal)
        case DocumentCreatedEvent():
            return await _document_created(session, env, client)
        case InviteSentEvent():
            return _invite_sent(env)
        case DeliveryLineEvent():
            # Стадию сделки задаёт DealRef события (как у любого события со сделкой). Запись в
            # ленту и сообщение
            # ответственному строятся в `process_event` из `settings.texts`, клиенту бот молчит.
            return None
    return None
