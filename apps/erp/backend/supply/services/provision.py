"""Обеспечение принятого КП (D26G-1, SPEC-v3 §3.1 ш. 6): резерв склада и черновик заказа поставщику на дефицит.

Клиент принял КП (`crm.services.quotes.lifecycle_accept.perform_quote_acceptance`) — ERP сам:

1. резервирует свободный остаток под строки-товары КП (`inventory.services.stock.reserve_for_quote`);
2. на то, чего на складе нет и что ещё не заказано в живых заказах (черновик, отправлен, подтверждён — за вычетом
   принятого), заводит черновики ЗП — по одному на поставщика. Поставщик строки — выбранный в расчёте (`item.offer`),
   иначе лучшее действующее предложение, как в колонке «Поставщик · срок» расчёта
   (`crm.services.calculation.line_supplier_offer`). Цена строки — цена этого предложения, если у всех строк заказа одна
   валюта;
3. строки дефицита без предложения поставщика заказом не становятся (у ЗП поставщик обязателен): запись в журнале
   проекта «Дефицит без поставщика» и колокольчик снабженцу задания — он выбирает поставщика в «Склад · Создать заказ ·
   На дефицит заявки» (`orders.create_from_deal` считает тот же дефицит).

Идемпотентно: повторный вызов (повтор события, ручной перезапуск) не создаёт дублей — резерв строки один и не больше её
количества, а заказывается только незаказанный остаток. Снабженцу задания уходит одно уведомление о созданных черновиках.

Отклонение КП и отмена проекта: `inventory.services.stock.release_for_deal` снимает резервы и отменяет черновики,
заведённые только под эту заявку (`cancel_drafts_for_deal`).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from inventory.access import StockError
from inventory.services import stock
from supply.models import OrderLogKind, OrderStatus, SupplierOrder, SupplierOrderLine
from supply.services import orders

logger = logging.getLogger(__name__)

LIVE_STATUSES = (OrderStatus.DRAFT, OrderStatus.SENT, OrderStatus.CONFIRMED)


def ordered_by_item(item_ids) -> dict[int, int]:
    """Сколько по строкам КП уже заказано и ещё не принято в живых заказах (черновик, отправлен, подтверждён)."""
    ids = [i for i in set(item_ids) if i]
    if not ids:
        return {}
    rows = (
        SupplierOrderLine.objects.filter(quote_item_id__in=ids, order__status__in=LIVE_STATUSES)
        .values("quote_item_id")
        .annotate(total=Sum("quantity") - Sum("received_quantity"))
    )
    return {row["quote_item_id"]: max(row["total"] or 0, 0) for row in rows}


def _supplier_or_none(offer) -> Optional[Any]:
    if offer is None:
        return None
    try:
        return orders.get_supplier(offer.supplier_id)
    except StockError:
        return None  # поставщик в архиве или это своя компания — заказ не на кого завести


def _create_draft(deal, quote, supplier, rows: list[tuple[Any, int, Any]]) -> SupplierOrder:
    """Черновик ЗП от имени системы (прав не проверяет — их проверил акцепт КП)."""
    currencies = {offer.currency_id for _item, _qty, offer in rows}
    one_currency = len(currencies) == 1 and None not in currencies
    lines = [
        orders.LineInput(
            quantity=quantity,
            product_id=item.product_id,
            deal_id=deal.pk,
            quote_item_id=item.pk,
            unit_price=offer.base_price if one_currency and offer.base_price else None,
            price_given=True,
            link_given=True,
        )
        for item, quantity, offer in rows
    ]
    resolved = orders._resolve_lines(lines)
    number, year, seq = stock.next_number("PO", "ЗП")
    note = f"Дефицит проекта {deal.number or ''} по принятому КП {quote.number or f'v{quote.version}'}".replace(
        "  ", " "
    )
    order = SupplierOrder.objects.create(
        number=number,
        number_year=year,
        number_seq=seq,
        supplier=supplier,
        currency_id=next(iter(currencies)) if one_currency else None,
        note=note.strip(),
        created_by=None,
    )
    orders._write_lines(order, resolved, None)
    orders._log(order, OrderLogKind.CREATED, None, f"{supplier.name} · автоматически при принятии КП")
    return order


def _notify_supply(deal, title: str, message: str, event_code: str, params: dict) -> None:
    """Колокольчик снабженцам задания расчёта (зона «товары»); задания нет — менеджеру заявки."""
    from crm.models import CalcZone
    from crm.services.calc_tasks import visa_assignees
    from crm.services.calculation import latest_task
    from notifications.models import Notification, NotificationType
    from notifications.services import push_notification_ws

    user_ids = [
        user_id
        for _crm_id, zone, user_id in visa_assignees(latest_task(deal.pk), persist=False)
        if user_id and zone == CalcZone.GOODS
    ]
    if not user_ids and deal.manager_id:
        user_ids = [deal.manager_id]
    ntype = NotificationType.objects.filter(code="INFO").first()
    for user_id in dict.fromkeys(user_ids):
        notification = Notification.objects.create(
            user_id=user_id,
            type=ntype,
            title=title,
            message=message,
            link=f"#deal/{deal.pk}",
            event_code=event_code,
            event_params=params,
        )
        transaction.on_commit(lambda n=notification: push_notification_ws(n))


@transaction.atomic
def provision_accepted_quote(quote) -> dict:
    """Резерв склада и черновики ЗП на дефицит по принятому КП. Возвращает сводку для журнала и тестов:
    `{"shortage": {item_id: qty}, "orders": [номера], "without_supplier": [item_id]}`."""
    from crm.models import QuoteItem
    from crm.services.calculation import line_supplier_offer

    deal = quote.deal
    shortage = stock.reserve_for_quote(quote)
    summary: dict[str, Any] = {"shortage": shortage, "orders": [], "without_supplier": []}
    if not shortage:
        return summary
    items = {
        item.pk: item
        for item in QuoteItem.objects.select_related("product__uom", "product__domain_type", "offer__supplier").filter(
            pk__in=shortage
        )
    }
    ordered = ordered_by_item(shortage)
    groups: dict[int, tuple[Any, list[tuple[Any, int, Any]]]] = {}
    without: list[Any] = []
    for item_id, missing in shortage.items():
        quantity = missing - ordered.get(item_id, 0)
        if quantity <= 0:
            continue
        item = items[item_id]
        offer = line_supplier_offer(item)
        supplier = _supplier_or_none(offer)
        if supplier is None:
            without.append((item, quantity))
            continue
        groups.setdefault(supplier.pk, (supplier, []))[1].append((item, quantity, offer))
    for supplier, rows in groups.values():
        order = _create_draft(deal, quote, supplier, rows)
        summary["orders"].append(order.number)
    summary["without_supplier"] = [item.pk for item, _qty in without]
    if summary["orders"]:
        stock._log_deal(
            deal,
            None,
            "Черновик заказа поставщику на дефицит",
            ", ".join(summary["orders"]),
            "supply.draft_on_accept",
            {"orders": summary["orders"]},
        )
        _notify_supply(
            deal,
            "Черновик заказа поставщику на дефицит",
            f"Проект {deal.number}: КП принято, на дефицит заведены черновики {', '.join(summary['orders'])} — "
            "проверьте и отправьте поставщику.",
            "supply.draft_on_accept",
            {"deal_id": deal.pk, "orders": summary["orders"]},
        )
    if without:
        names = "; ".join(f"{item.imported_raw_name or item.product.name}: {quantity}" for item, quantity in without)
        stock._log_deal(
            deal,
            None,
            "Дефицит без поставщика",
            names,
            "supply.shortage_without_supplier",
            {"lines": len(without)},
        )
        _notify_supply(
            deal,
            "Дефицит без поставщика",
            f"Проект {deal.number}: КП принято, у позиций нет предложения поставщика ({names}). Выберите поставщика: "
            "Склад · Создать заказ · На дефицит заявки.",
            "supply.shortage_without_supplier",
            {"deal_id": deal.pk, "lines": len(without)},
        )
    return summary


@transaction.atomic
def cancel_drafts_for_deal(deal, *, reason: str = "") -> int:
    """Отменить черновики ЗП, все строки которых — под эту заявку (КП отклонено, проект отменён). Отправленные и
    подтверждённые заказы и черновики со строками других проектов не трогаются. Повторный вызов — 0."""
    ids = list(
        SupplierOrder.objects.filter(status=OrderStatus.DRAFT, lines__deal=deal).values_list("pk", flat=True).distinct()
    )
    drafts = SupplierOrder.objects.select_for_update().filter(pk__in=ids, status=OrderStatus.DRAFT).order_by("pk")
    cancelled = 0
    for order in drafts:
        if order.lines.exclude(deal=deal).exists():
            continue
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = timezone.now()
        order.cancel_reason = (reason or "Резервы проекта сняты")[:500]
        order.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
        orders._log(order, OrderLogKind.CANCELLED, None, order.cancel_reason)
        cancelled += 1
    return cancelled
