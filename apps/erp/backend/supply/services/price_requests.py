"""«Запросить цену у поставщика» из расчёта (D2-2, SPEC-v3 §7.4 «Расчёт»): письмо поставщику и журнал запроса.

Снабженец выбирает поставщика и строки-товары расчёта; ERP составляет письмо по шаблону `price_request` (адрес поставщика —
почта компании или основного контакта; ответить можно на почту сотрудника: `Reply-To`) и пишет журнал: кто, когда, кому, по
каким строкам, ушло ли письмо. Ответ поставщика вносится вручную: цена — в строку расчёта («Закупка»), отметка «ответ
получен» — здесь (`mark_answered`). Попытка, не ушедшая из-за почты, остаётся в журнале со статусом «не отправлен» (письмо
можно отправить заново новым запросом) — 201, не 5xx: журнал важнее статуса почты.
"""

from __future__ import annotations

import logging
from typing import Optional

from django.db import transaction
from django.utils import timezone
from inventory.access import StockError, person_name, require_staff, require_supply
from supply.models import PriceRequest, PriceRequestLine, PriceRequestStatus
from supply.services.orders import get_supplier, supplier_email

logger = logging.getLogger(__name__)

MAX_LINES = 100
MAX_ROWS = 100


def _deal_and_items(deal_id: int, item_ids: list[int]):
    from sales.models import Deal

    from crm.services.calculation import calc_quote, zone_of

    deal = Deal.objects.select_related("company").filter(pk=deal_id).first()
    if deal is None:
        raise StockError("DEAL_NOT_FOUND", 404)
    quote = calc_quote(deal)
    if quote is None:
        raise StockError("CALC_NOT_STARTED", 409)
    ids = list(dict.fromkeys(item_ids))
    items = {i.pk: i for i in quote.items.billable().select_related("product__domain_type", "calc").filter(pk__in=ids)}
    # Объектная проверка: строки должны быть строками расчёта этой заявки.
    if len(items) != len(ids):
        raise StockError("LINE_NOT_FOUND", 404)
    ordered = [items[i] for i in ids]
    if any(zone_of(item) != "goods" for item in ordered):
        raise StockError("LINE_NOT_GOODS", 409)  # услугу у поставщика товаров не запрашивают
    return deal, ordered


def create(
    user,
    deal_id: int,
    supplier_id: int,
    item_ids: list[int],
    *,
    note: str = "",
    to_email: str = "",
) -> PriceRequest:
    from notifications.emails import send_templated_email

    require_supply(user)
    if not item_ids:
        raise StockError("LINES_REQUIRED", 400)
    if len(item_ids) > MAX_LINES:
        raise StockError("TOO_MANY_LINES", 400)
    deal, items = _deal_and_items(deal_id, item_ids)
    supplier = get_supplier(supplier_id)
    recipient = (to_email or "").strip() or supplier_email(supplier)
    if not recipient:
        raise StockError("SUPPLIER_EMAIL_REQUIRED", 409)
    reference = deal.number or f"№{deal.pk}"
    subject = f"Запрос цены и срока поставки — {reference}"
    with transaction.atomic():
        request = PriceRequest.objects.create(
            supplier=supplier,
            deal=deal,
            requested_by=user if getattr(user, "pk", None) else None,
            to_email=recipient,
            subject=subject,
            note=(note or "").strip()[:1000],
            status=PriceRequestStatus.SENT,
        )
        PriceRequestLine.objects.bulk_create(
            PriceRequestLine(
                request=request,
                quote_item=item,
                name=(
                    item.imported_raw_name
                    or (item.product.name if item.product_id else "")
                    or f"Позиция {item.position}"
                )[:500],
                article=(item.mpn or (item.product.manufacturer_part_number if item.product_id else "") or "")[:120],
                quantity=item.quantity,
                unit=item.unit,
            )
            for item in items
        )
    context = {
        "supplier_name": supplier.name,
        "reference": reference,
        "sender_name": person_name(user),
        "sender_email": getattr(user, "email", "") or "",
        "note": request.note,
        "lines": [
            {"name": line.name, "article": line.article, "quantity": line.quantity, "unit": line.unit}
            for line in request.lines.all()
        ],
    }
    try:
        log = send_templated_email(
            "price_request",
            context,
            to=[recipient],
            channel="transactional",
            user=None,
            language=supplier.language or None,
            reply_to=[user.email] if getattr(user, "email", "") else None,
            fail_silently=True,
        )
        failed = log.status != "SENT"
        error = (log.error or "")[:500] if failed else ""
    except Exception as exc:  # noqa: BLE001 — журнал запроса важнее исключения почты
        logger.exception("Запрос цены %s не отправлен", request.pk)
        failed, error = True, f"{exc.__class__.__name__}: {exc}"[:500]
    if failed:
        request.status = PriceRequestStatus.FAILED
        request.error = error
        request.save(update_fields=["status", "error"])
    _log_deal(deal, user, request, supplier.name, failed)
    return request


def _log_deal(deal, user, request: PriceRequest, supplier_name: str, failed: bool) -> None:
    from sales.models import ActivityLog

    ActivityLog.objects.create(
        action="Запрос цены у поставщика" + (" (не отправлен)" if failed else ""),
        detail=f"{supplier_name}: {request.lines.count()} поз.",
        user=user if getattr(user, "pk", None) else None,
        level="WARNING" if failed else "INFO",
        entity_type="deal",
        entity_id=deal.pk,
        deal=deal,
        company_id=deal.company_id,
        event_code="rfq.price_requested",
        event_params={"supplier": supplier_name, "request_id": request.pk, "lines": request.lines.count()},
    )


@transaction.atomic
def mark_answered(user, request_id: int, note: str = "") -> PriceRequest:
    require_supply(user)
    request = PriceRequest.objects.select_for_update().filter(pk=request_id).first()
    if request is None:
        raise StockError("REQUEST_NOT_FOUND", 404)
    if request.status != PriceRequestStatus.SENT:
        raise StockError("REQUEST_NOT_SENT", 409)
    if request.answered_at is not None:
        raise StockError("ALREADY_ANSWERED", 409)
    request.answered_at = timezone.now()
    request.answered_by = user if getattr(user, "pk", None) else None
    request.answer_note = (note or "").strip()[:1000]
    request.save(update_fields=["answered_at", "answered_by", "answer_note"])
    return request


def present(request: PriceRequest) -> dict:
    return {
        "id": request.pk,
        "supplier": {"id": request.supplier_id, "name": request.supplier.name},
        "deal_id": request.deal_id,
        "deal_number": request.deal.number if request.deal_id and request.deal.number else None,
        "requested_at": request.requested_at.isoformat(),
        "requested_by_name": person_name(request.requested_by) if request.requested_by_id else None,
        "to_email": request.to_email,
        "subject": request.subject,
        "note": request.note or None,
        "status": request.status,
        "error": request.error or None,
        "answered_at": request.answered_at.isoformat() if request.answered_at else None,
        "answered_by_name": person_name(request.answered_by) if request.answered_by_id else None,
        "answer_note": request.answer_note or None,
        "lines": [
            {
                "quote_item_id": line.quote_item_id,
                "name": line.name,
                "article": line.article,
                "quantity": line.quantity,
                "unit": line.unit,
            }
            for line in request.lines.all()
        ],
    }


def list_requests(user, *, deal_id: Optional[int] = None, supplier_id: Optional[int] = None) -> list[dict]:
    require_staff(user)
    qs = PriceRequest.objects.select_related("supplier", "deal", "requested_by", "answered_by").prefetch_related(
        "lines"
    )
    if deal_id:
        qs = qs.filter(deal_id=deal_id)
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    return [present(r) for r in qs[:MAX_ROWS]]
