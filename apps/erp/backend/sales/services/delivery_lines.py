"""Строки поставки (FIX-22): создание из подтверждённого заказа, перенос хода исполнения, приёмка и замечание клиента.

Бизнес-логика только здесь; портал (`portal/views.py`) — тонкая обёртка. Ошибки — кортеж `(объект, None)` /
`(None, КОД)`, как у остальных сервисов ERP; код портал переводит в свой `ErrorCode`.

Откуда берутся строки. Заказ клиента — оплачиваемые позиции (`QuoteItem.objects.billable()`) последней версии КП в
статусе `APPROVED`. Пока склада и заказов поставщикам нет (M4), ход исполнения ведёт `Fulfillment` сделки (один на
сделку), и `sync_delivery_lines` переносит его статус, срок, трек и дату отгрузки на все строки сделки. Строка,
которую клиент принял или оспорил, больше не перезаписывается: это его решение, а не ход склада. События для CRM
(`delivery.line_accepted|disputed`, FIX-37) уходят из `accept_delivery_line` / `dispute_delivery_line`.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Tuple

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from sales.models import ActivityLog, DeliveryLine, DeliveryLineStatus, Fulfillment, Quote, QuoteItem

from crm.constants import FulfillmentStatusCode, QuoteStatusCode

logger = logging.getLogger(__name__)

#: Статус исполнения сделки → статус строки поставки. `READY_TO_SHIP` у `Fulfillment` нет (склад — M4).
FULFILLMENT_TO_LINE_STATUS = {
    FulfillmentStatusCode.PENDING: DeliveryLineStatus.ASSEMBLING,
    FulfillmentStatusCode.SHIPPED: DeliveryLineStatus.SHIPPED,
    FulfillmentStatusCode.IN_TRANSIT: DeliveryLineStatus.IN_TRANSIT,
    FulfillmentStatusCode.DELIVERED: DeliveryLineStatus.DELIVERED,
    FulfillmentStatusCode.ACCEPTED: DeliveryLineStatus.ACCEPTED,
    FulfillmentStatusCode.DISPUTED: DeliveryLineStatus.DISPUTED,
}

#: Решения клиента: после них ход склада строку не меняет.
CLIENT_FINAL_STATUSES = (DeliveryLineStatus.ACCEPTED, DeliveryLineStatus.DISPUTED)


def _line_status(fulfillment: Fulfillment) -> str:
    code = fulfillment.status.code if fulfillment.status_id else FulfillmentStatusCode.PENDING
    return FULFILLMENT_TO_LINE_STATUS.get(code, DeliveryLineStatus.ASSEMBLING)


def _unit_name(item: QuoteItem) -> str:
    if item.unit:
        return item.unit
    product = item.product
    return product.uom.name if product is not None and product.uom_id else ""


def _title(item: QuoteItem) -> str:
    product = item.product
    return ((product.name if product is not None else "") or item.imported_raw_name or "")[:500]


def _approved_quotes_by_deal(deal_ids: list[int]) -> dict[int, Quote]:
    quotes = (
        Quote.objects.filter(deal_id__in=deal_ids, status__code=QuoteStatusCode.APPROVED)
        .order_by("deal_id", "-version")
        .prefetch_related(
            # Позиции заказа в порядке КП; товар и единица — одним запросом, чтобы не ходить за ними по строкам.
            Prefetch(
                "items",
                queryset=QuoteItem.objects.billable().select_related("product__uom").order_by("position", "id"),
                to_attr="order_items",
            )
        )
    )
    by_deal: dict[int, Quote] = {}
    for quote in quotes:
        by_deal.setdefault(quote.deal_id, quote)  # старшая версия подтверждённого КП
    return by_deal


def sync_delivery_lines(fulfillments: Iterable[Fulfillment]) -> int:
    """Довести строки поставки до состояния исполнения сделок. Идемпотентно. Возвращает число созданных строк.

    Создаёт недостающие строки подтверждённого заказа и обновляет статус, срок, трек и дату отгрузки у строк,
    которые клиент ещё не принял и не оспорил. Сам `Fulfillment` не меняет.
    """
    fulfillments = [f for f in fulfillments]
    if not fulfillments:
        return 0
    deal_ids = [f.deal_id for f in fulfillments]
    quotes = _approved_quotes_by_deal(deal_ids)
    existing: dict[int, DeliveryLine] = {
        line.quote_item_id: line
        for line in DeliveryLine.objects.filter(deal_id__in=deal_ids).select_related("quote_item")
    }

    to_create: list[DeliveryLine] = []
    to_update: list[tuple[list[int], dict]] = []  # (id строк, новые значения) — по сделке
    stale_ids: list[int] = []
    for fulfillment in fulfillments:
        quote = quotes.get(fulfillment.deal_id)
        if quote is None:
            continue  # заказа нет — строк нет, выдумывать нечего
        # Заказ пересобран новой версией КП: строки старой, которых клиент не касался, больше не поставка.
        stale_ids += [
            line.pk
            for line in existing.values()
            if line.deal_id == fulfillment.deal_id
            and line.quote_item.quote_id != quote.pk
            and line.status not in CLIENT_FINAL_STATUSES
        ]
        wanted = {
            "status": _line_status(fulfillment),
            "eta": fulfillment.expected_delivery_date,
            "tracking": fulfillment.tracking_number or "",
            "shipped_at": fulfillment.shipped_at,
            "accepted_at": fulfillment.accepted_at if _line_status(fulfillment) in CLIENT_FINAL_STATUSES else None,
        }
        changed_ids: list[int] = []
        for number, item in enumerate(quote.order_items, start=1):
            line = existing.get(item.pk)
            if line is None:
                to_create.append(
                    DeliveryLine(
                        deal_id=fulfillment.deal_id,
                        quote_item=item,
                        line_no=number,
                        title=_title(item),
                        quantity=item.quantity,
                        unit=_unit_name(item),
                        **wanted,
                    )
                )
            elif line.status not in CLIENT_FINAL_STATUSES and any(
                getattr(line, field) != value for field, value in wanted.items()
            ):
                changed_ids.append(line.pk)
        if changed_ids:
            to_update.append((changed_ids, wanted))

    # Строки прочитаны заранее, а клиент мог принять или оспорить их, пока sync считал: запись и удаление идут с
    # условием «решения клиента нет» прямо в SQL (а не по прочитанному снимку), иначе решение пропало бы.
    if stale_ids:
        DeliveryLine.objects.filter(pk__in=stale_ids).exclude(status__in=CLIENT_FINAL_STATUSES).delete()
    if to_create:
        # Две вкладки портала открывают список одновременно: вторая вставка ничего не ломает.
        DeliveryLine.objects.bulk_create(to_create, ignore_conflicts=True)
    for ids, values in to_update:
        DeliveryLine.objects.filter(pk__in=ids).exclude(status__in=CLIENT_FINAL_STATUSES).update(
            **values, updated_at=timezone.now()
        )
    return len(to_create)


def sync_company_delivery_lines(company) -> None:
    """Строки поставки по всем сделкам компании клиента (портал зовёт перед чтением и перед приёмкой)."""
    sync_delivery_lines(Fulfillment.objects.filter(deal__company=company).select_related("status"))


def _manager_recipient_ids(deal) -> list[int]:
    """Кому уйдёт замечание клиента: ответственный по сделке, иначе продающие сотрудники своей компании."""
    from crm.services.deal_notifications import seller_team_user_ids

    for holder in (deal.assigned_to_id, deal.manager_id):
        if holder:
            return [holder]
    return seller_team_user_ids(deal)


def _can_act(contact, line: DeliveryLine) -> bool:
    return bool(contact is not None and contact.can_act and contact.company_id == line.deal.company_id)


def _emit_decision(line: DeliveryLine, contact) -> None:
    """Событие для CRM о решении клиента (FIX-37). Сбой события не отменяет решение клиента: он уже принял строку.

    Запись события пишется в транзакции решения (в своей точке сохранения, чтобы сбой не сорвал транзакцию), задача
    доставки встаёт в очередь после коммита (`integration.services.webhooks.emit_event`).
    """
    from integration.services import webhooks

    try:
        with transaction.atomic():
            webhooks.emit_delivery_line_decision(line, contact)
    except Exception:
        logger.exception("Не удалось создать событие о решении клиента по строке поставки #%s", line.pk)
        # След для ручной досылки: какое событие и по какой строке не ушло (точка сохранения уже откачена).
        event_type = webhooks.DELIVERY_LINE_EVENTS.get(str(line.status), "delivery.line_*")
        ActivityLog.objects.create(
            action="Событие для CRM не создано",
            detail=f"Событие {event_type} по строке {line.line_no} (id {line.pk}) сделки #{line.deal_id} не создано, "
            "решение клиента сохранено; досылать вручную",
            event_code="delivery.line_event_failed",
            event_params={"line_id": line.pk, "event_type": event_type, "deal_id": line.deal_id},
            level="ERROR",
            deal=line.deal,
            company_id=line.deal.company_id,
        )


@transaction.atomic
def accept_delivery_line(line_id: int, contact) -> Tuple[Optional[DeliveryLine], Optional[str]]:
    """Клиент принимает строку: только `delivered` → `accepted`."""
    line = DeliveryLine.objects.select_for_update().select_related("deal").get(pk=line_id)
    if not _can_act(contact, line):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if line.status != DeliveryLineStatus.DELIVERED:
        return None, "DELIVERY_LINE_NOT_ACCEPTABLE"
    line.status = DeliveryLineStatus.ACCEPTED
    line.accepted_at = timezone.now()
    line.save(update_fields=["status", "accepted_at", "updated_at"])
    ActivityLog.objects.create(
        action="Поставка принята клиентом",
        detail=f"Строка {line.line_no} «{line.title}» по сделке #{line.deal_id} принята: {contact.name}",
        event_code="delivery.line_accepted",
        event_params={"line_id": line.pk, "line_no": line.line_no, "deal_id": line.deal_id, "contact_id": contact.pk},
        level="SUCCESS",
        deal=line.deal,
        company_id=line.deal.company_id,
    )
    _emit_decision(line, contact)
    return line, None


@transaction.atomic
def dispute_delivery_line(line_id: int, contact, reason: str) -> Tuple[Optional[DeliveryLine], Optional[str]]:
    """Клиент оспаривает строку: только `delivered` → `disputed`, причина в `remark`, менеджеру — задача."""
    clean_reason = (reason or "").strip()
    if not clean_reason:
        return None, "REASON_REQUIRED"
    line = DeliveryLine.objects.select_for_update().select_related("deal").get(pk=line_id)
    if not _can_act(contact, line):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    if line.status != DeliveryLineStatus.DELIVERED:
        return None, "DELIVERY_LINE_NOT_ACCEPTABLE"
    line.status = DeliveryLineStatus.DISPUTED
    line.remark = clean_reason
    line.accepted_at = timezone.now()
    line.save(update_fields=["status", "remark", "accepted_at", "updated_at"])
    params = {
        "line_id": line.pk,
        "line_no": line.line_no,
        "deal_id": line.deal_id,
        "contact_id": contact.pk,
        "reason": clean_reason,
    }
    ActivityLog.objects.create(
        action="Поставка оспорена клиентом",
        detail=f"Строка {line.line_no} «{line.title}» по сделке #{line.deal_id}: {clean_reason}",
        event_code="delivery.line_disputed",
        event_params=params,
        level="WARNING",
        deal=line.deal,
        company_id=line.deal.company_id,
    )
    _emit_decision(line, contact)
    transaction.on_commit(lambda: _notify_dispute(line, clean_reason))
    return line, None


def _notify_dispute(line: DeliveryLine, reason: str) -> None:
    """Задача менеджеру сделки: уведомление ERP с разбором причины (центр уведомлений бэк-офиса)."""
    from crm.services.deal_notifications import notify_deal_users
    from notifications.services import spa_link

    notify_deal_users(
        _manager_recipient_ids(line.deal),
        deal=line.deal,
        title="Клиент оспорил поставку",
        message=f"Сделка #{line.deal_id}, строка {line.line_no} «{line.title}»: {reason}",
        link=spa_link("fulfillments"),
        type_code="WARNING",
        event_code="delivery.line_disputed",
        event_params={"deal_id": line.deal_id, "line_no": line.line_no, "title": line.title, "reason": reason},
    )
