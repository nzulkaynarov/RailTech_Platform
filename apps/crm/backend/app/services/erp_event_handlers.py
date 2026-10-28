"""Применение входящих событий ERP к зеркалу CRM (FIX-35, B4): по классу модели `data`.

`dispatch` получает событие шины (`app.bus.erp_event.ErpEvent`, модели — сгенерированные
`rt_contracts.events.erp`), меняет зеркало сделки и индекс документов клиента и возвращает текст
заметки в ленту лида (если она нужна). Тексты клиенту и сотруднику строит
`services/erp_bot_messages.py` из `settings.texts`; здесь их нет. Читатель терпимый: поле, которого
модель не знает, сюда не доходит.
"""

from datetime import UTC, datetime
from decimal import Decimal

from rt_contracts.events.erp import (
    ActAcceptedV1,
    ActIssuedV1,
    ActReturnedV1,
    ContractSignedV1,
    DealLostV1,
    DealStageChangedV1,
    DealWonV1,
    DeliveryEtaChangedV1,
    DeliveryLineAcceptedV1,
    DeliveryLineDisputedV1,
    DeliveryStatusChangedV1,
    DocumentCreatedV1,
    InviteSentV1,
    InvoiceIssuedV1,
    InvoiceOverdueV1,
    InvoicePaidV1,
    QuoteAcceptedV1,
    QuoteRejectedV1,
    QuoteSentV1,
    QuoteViewedV1,
    RequestCreatedV1,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.erp_event import ErpEvent, plain
from app.domain.deals import DealStage, plan_erp_outcome
from app.models.clients import Client, ClientContact, Document
from app.models.deals import Deal

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


def _request_created(env: ErpEvent) -> str:
    payload = env.payload
    return (
        f"В бэк-офисе создана заявка #{payload.erp_request_id or '—'} "
        f"(источник: {plain(payload.source)})."
    )


def _stage_changed(env: ErpEvent, deal: Deal | None) -> str:
    payload = env.payload
    to = str(plain(payload.to))
    _set_stage(deal, to)
    note = f"Стадия сделки в бэк-офисе: {plain(payload.from_)} → {to}"
    return note + (f" ({payload.reason})" if payload.reason else "")


def _outcome(env: ErpEvent, deal: Deal | None, deal_title: str) -> str:
    payload = env.payload
    won = env.event == "deal.won"
    amount, currency = str(plain(payload.amount)), str(plain(payload.currency))
    if deal is not None and outcome_is_current(deal, env.occurred_at):
        reason = None if won else payload.lost_reason
        plan = plan_erp_outcome(env.event, _local_stage(deal), reason)
        deal.stage = plan.stage.value
        deal.closed_at = env.occurred_at
        deal.external_stage = "won" if won else "lost"
        if won:
            deal.amount = Decimal(amount)
            deal.currency = currency
        else:
            deal.lost_reason = plan.lost_reason
    if won:
        return f"Сделка «{deal_title}» успешно закрыта (won) на сумму {amount} {currency}."
    reason = payload.lost_reason or "не указана"
    return f"Сделка «{deal_title}» закрыта отказом (lost). Причина: {reason}."


def _quote_sent(env: ErpEvent, deal: Deal | None) -> str:
    payload = env.payload
    _set_stage(deal, "quote_sent")
    parts = [f"Клиенту отправлено КП #{payload.erp_quote_id} v{payload.version}"]
    total, currency = plain(payload.total), plain(payload.currency)
    if total and currency:
        parts.append(f"на сумму {total} {currency}")
    if payload.public_url:
        parts.append(f"Ссылка: {payload.public_url}")
    return ". ".join(parts) + "."


def _quote_outcome(env: ErpEvent, deal: Deal | None, contact_name: str | None) -> str:
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


def _contract_signed(env: ErpEvent, deal: Deal | None) -> str:
    _set_stage(deal, "contract")
    return f"Договор {env.payload.number or ''} подписан ({plain(env.payload.by)})."


def mark_invoiced(deal: Deal | None, occurred_at: datetime) -> None:
    """Факт «по сделке выставлен счёт» (B-D18-1): самое раннее событие счёта, порядок прихода
    не важен; опоздавшее событие отметку не снимает (зона переписки «Счета и оплаты»)."""
    if deal is None:
        return
    moment = aware(occurred_at)
    if deal.invoice_issued_at is None or moment < aware(deal.invoice_issued_at):
        deal.invoice_issued_at = moment


def _invoice(env: ErpEvent, deal: Deal | None) -> str:
    payload = env.payload
    # Оплата и просрочка тоже значат, что счёт выставлен (если `invoice.issued` ещё в пути).
    mark_invoiced(deal, env.occurred_at)
    amount, currency = plain(payload.amount), plain(payload.currency)
    if env.event == "invoice.issued":
        _set_stage(deal, "invoiced")
        return (
            f"Выставлен счёт {payload.number} на сумму {amount} {currency} "
            f"со сроком оплаты до {payload.due_date}."
        )
    if env.event == "invoice.paid":
        _set_stage(deal, "paid")
        return f"Счёт {payload.number} на сумму {amount} {currency} оплачен."
    return f"Счёт {payload.number} просрочен (срок оплаты был {payload.due_date})."


def _delivery(env: ErpEvent, deal: Deal | None) -> str:
    payload = env.payload
    if env.event == "delivery.status_changed":
        _set_stage(deal, "fulfilment")
        eta = f", ожидается {payload.eta}" if payload.eta else ""
        return f"Статус поставки ({payload.line_summary}): {plain(payload.status)}{eta}"
    return (
        f"Изменилась дата поставки ({payload.line_summary}): "
        f"{payload.previous_eta or '—'} → {payload.eta}."
    )


def _act(env: ErpEvent, deal: Deal | None) -> str:
    payload = env.payload
    if env.event == "act.issued":
        _set_stage(deal, "closing")
        return f"Сформирован акт {payload.number}."
    if env.event == "act.accepted":
        return f"Акт {payload.number} принят клиентом."
    return f"Акт {payload.number} возвращён клиентом с замечаниями: {payload.reason or ''}."


async def _document_created(session: AsyncSession, env: ErpEvent, client: Client) -> str:
    """Индекс документов клиента: upsert по `(client_id, erp_document_id)`, дублей не плодит."""
    payload = env.payload
    kind = str(plain(payload.kind))
    title = payload.title or f"{kind} {payload.number}"
    values = {
        "type": DOC_KIND_MAP.get(kind, "other"),
        "title": title,
        "number": payload.number or None,
        "filename": f"{kind}_{payload.number}.pdf",
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


def _invite_sent(env: ErpEvent) -> str:
    channels = ", ".join(str(plain(channel)) for channel in env.payload.channels)
    return f"Контакту отправлено приглашение в кабинет через каналы: {channels}."


async def dispatch(
    session: AsyncSession, env: ErpEvent, client: Client, deal: Deal | None
) -> str | None:
    """Меняет зеркало сделки и индекс документов; возвращает текст заметки в ленту лида или
    `None`.
    """
    env_deal = env.deal
    deal_title = env_deal.title if env_deal else (deal.title if deal else "Сделка")
    match env.data:
        case RequestCreatedV1():
            return _request_created(env)
        case DealStageChangedV1():
            return _stage_changed(env, deal)
        case DealWonV1() | DealLostV1():
            return _outcome(env, deal, deal_title)
        case QuoteSentV1():
            return _quote_sent(env, deal)
        case QuoteViewedV1() | QuoteAcceptedV1() | QuoteRejectedV1():
            who = None
            if env.event != "quote.viewed":
                who = await _crm_contact_name(session, client, env.payload.crm_contact_id)
            return _quote_outcome(env, deal, who)
        case ContractSignedV1():
            return _contract_signed(env, deal)
        case InvoiceIssuedV1() | InvoicePaidV1() | InvoiceOverdueV1():
            return _invoice(env, deal)
        case DeliveryStatusChangedV1() | DeliveryEtaChangedV1():
            return _delivery(env, deal)
        case ActIssuedV1() | ActAcceptedV1() | ActReturnedV1():
            return _act(env, deal)
        case DocumentCreatedV1():
            return await _document_created(session, env, client)
        case InviteSentV1():
            return _invite_sent(env)
        case DeliveryLineAcceptedV1() | DeliveryLineDisputedV1():
            # Стадию сделки задаёт DealRef события (как у любого события со сделкой). Запись в
            # ленту и сообщение ответственному строятся в `ErpEventsService.apply` из
            # `settings.texts`, клиенту бот молчит.
            return None
    return None
