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

from core.person_ref import person_ref

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
    partner_names: Optional[dict[int, dict]] = None,
) -> PriceRequest:
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
    # The partner sees what is asked, not our project number (СЦ-10): «Рельс Р65 и ещё 2 позиции» — НАШИМИ словами:
    # название и артикул карточки каталога; слова клиента — только после подтверждения сотрудником (В-2).
    rows = partner_lines(items, partner_names)
    missing = [row for row in rows if row["name"] is None]
    if missing:
        raise StockError("PARTNER_NAME_REQUIRED", 409)
    reference = _summary(rows[0]["name"], len(rows) - 1)
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
                quote_item=row["item"],
                name=row["name"][:500],
                article=row["article"][:120],
                quantity=row["item"].quantity,
                unit=row["item"].unit,
            )
            for row in rows
        )
    failed = _dispatch(user, request, supplier, recipient, reference)
    _log_deal(deal, user, request, supplier.name, failed)
    return request


def _dispatch(user, request: PriceRequest, supplier, recipient: str, reference: str) -> bool:
    """Письма и колокольчик партнёру; вернуть True, если письмо не ушло (статус FAILED записан).

    ДК-5: партнёру с Кабинетом запрос уходит одним письмом на контакт, который может ответить, — PDF и кнопка на личную
    ссылку этого контакта (уведомление `partner_rfq_sent`). Прежнее письмо «ответьте на это письмо» нужно только адресу,
    которого среди этих контактов нет (общая почта поставщика), и партнёру без Кабинета; сотрудник отмечает такой ответ сам.
    """
    from portal.models import NoticeChannel
    from supply.services.orders import partner_confirms_in_cabinet

    from notifications.emails import send_templated_email
    from notifications.text_format import text_qty

    in_cabinet = partner_confirms_in_cabinet(supplier)
    notices = _notify_contacts(request, letters=True) if in_cabinet else []
    emailed = {n.contact.email.strip().lower() for n in notices if n.channel == NoticeChannel.EMAIL}
    if in_cabinet and recipient.strip().lower() in emailed:
        return False  # одно письмо: адрес запроса — контакт, который уже получил письмо со ссылкой
    context = {
        "supplier_name": supplier.name,
        "reference": reference,
        "sender_name": person_name(user),
        "sender_email": getattr(user, "email", "") or "",
        "note": request.note,
        "answer_in_cabinet": in_cabinet,
        "lines": [
            {"name": line.name, "article": line.article, "quantity": text_qty(line.quantity), "unit": line.unit}
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
        # W18A-P1: письмо передано почтовому сервису CRM — «В очереди» (QUEUED), итог придёт событием; не ушло —
        # только если передать не удалось (FAILED).
        failed = log is None or log.status == "FAILED"
        error = (log.error or "")[:500] if failed else ""
    except Exception as exc:  # noqa: BLE001 — журнал запроса важнее исключения почты
        logger.exception("Запрос цены %s не отправлен", request.pk)
        failed, error = True, f"{exc.__class__.__name__}: {exc}"[:500]
    if failed:
        request.status = PriceRequestStatus.FAILED
        request.error = error
        request.save(update_fields=["status", "error"])
    elif not in_cabinet:
        _notify_contacts(request, letters=False)
    return failed


def _notify_contacts(request: PriceRequest, *, letters: bool) -> list:
    """Колокольчик контактам партнёра; письмо со ссылкой — тем, кто может ответить (право — как в Кабинете), и только если
    партнёр отвечает в Кабинете (`letters`): иначе запрос уходит прежним письмом и второго письма нет."""
    try:
        from parties.models import Contact, active_contact_q
        from portal.services import notice_sources

        contacts = Contact.objects.filter(active_contact_q(), company=request.supplier)
        if letters:
            contacts = contacts.filter(can_act=False)
        skip = {pk: "no_right" if letters else "no_cabinet" for pk in contacts.values_list("pk", flat=True)}
        return notice_sources.partner_rfq_notices(request, email_skip=skip)
    except Exception:
        logger.exception("Не удалось отправить уведомление о запросе цены %s", request.pk)
        return []


def create_from_order(
    user, order_id: int, line_ids: Optional[list[int]] = None, *, note: str = "", to_email: str = ""
) -> PriceRequest:
    """«Запросить цену» из черновика заказа (СЦ-10): строки без цены уходят партнёру этого заказа; заказ остаётся
    черновиком, а ответ партнёра из кабинета вписывает цены в его строки (`partner_orders._price_draft`)."""
    from supply.models import OrderStatus
    from supply.services import orders

    require_supply(user)
    order = orders._order_or_404(order_id, lock=True)
    if order.status != OrderStatus.DRAFT:
        raise StockError("ORDER_NOT_DRAFT", 409)
    lines = list(order.lines.select_related("product", "deal"))
    if line_ids:
        by_id = {line.pk: line for line in lines}
        if any(pk not in by_id for pk in line_ids):
            raise StockError("LINE_NOT_FOUND", 404)
        chosen = [by_id[pk] for pk in dict.fromkeys(line_ids)]
    else:
        chosen = [line for line in lines if line.unit_price is None]
    if not chosen:
        raise StockError("NOTHING_TO_PRICE", 409)
    if len(chosen) > MAX_LINES:
        raise StockError("TOO_MANY_LINES", 400)
    recipient = (to_email or "").strip() or supplier_email(order.supplier)
    if not recipient:
        raise StockError("SUPPLIER_EMAIL_REQUIRED", 409)
    deals = {line.deal_id for line in chosen if line.deal_id}
    deal = chosen[0].deal if len(deals) == 1 and chosen[0].deal_id else None
    reference = _summary(chosen[0].name, len(chosen) - 1)  # без нашего номера заказа (СЦ-10, #694)
    with transaction.atomic():
        request = PriceRequest.objects.create(
            supplier=order.supplier,
            deal=deal,
            supplier_order=order,
            requested_by=user if getattr(user, "pk", None) else None,
            to_email=recipient,
            subject=f"Запрос цены и срока поставки — {reference}",
            note=(note or "").strip()[:1000],
            status=PriceRequestStatus.SENT,
        )
        PriceRequestLine.objects.bulk_create(
            PriceRequestLine(
                request=request,
                order_line=line,
                product=line.product,
                quote_item_id=line.quote_item_id,
                name=line.name[:500],
                article=(line.article or "")[:120],
                quantity=line.quantity,
                unit=line.unit,
            )
            for line in chosen
        )
    failed = _dispatch(user, request, order.supplier, recipient, reference)
    if deal is not None:
        _log_deal(deal, user, request, order.supplier.name, failed)
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


def partner_lines(items, partner_names: Optional[dict[int, dict]] = None) -> list[dict]:
    """Строки запроса цены ТАК, как их увидит партнёр (В-2, аудит конфиденциальности 2026-11-25).

    Название и артикул — нашей карточки каталога (`product.name`, `product.sku`). Слова клиента из заявки
    (`imported_raw_name`: название объекта, станция, своя компания, номер чертежа) партнёру не уходят никогда сами:
    строка без карточки получает название только из подтверждённого сотрудником «как назвать партнёру»
    (`partner_names[item.pk]["name"]`; там же можно переименовать и строку с карточкой). Нет ни карточки, ни подтверждения —
    `name=None` (`source="missing"`): отправить нельзя.
    """
    given = partner_names or {}
    rows = []
    for item in items:
        confirmed = given.get(item.pk) or {}
        staff_name = " ".join((confirmed.get("name") or "").split())
        product = item.product if item.product_id else None
        if staff_name:
            source, name = "staff", staff_name
        elif product is not None:
            source, name = "card", product.name
        else:
            source, name = "missing", None
        article = " ".join((confirmed.get("article") or "").split()) or (product.sku if product is not None else "")
        rows.append(
            {
                "item": item,
                "name": name,
                "article": article or "",
                "source": source,
                "client_name": item.imported_raw_name or "",
            }
        )
    return rows


def _preview_supplier(supplier_id: int):
    """Партнёр для предпросмотра: роль «поставщик» ему ставят в момент отправки (ЕД-6), поэтому до отправки подходит любая
    чужая не архивная компания; сама отправка проверяет `get_supplier`."""
    from parties.models import Company
    from supply.services.orders import _own_company_id

    company = Company.objects.exclude(pk=_own_company_id() or 0).filter(pk=supplier_id).first()
    if company is None or getattr(company, "is_archived", False):
        raise StockError("SUPPLIER_NOT_FOUND", 404)
    return company


def preview(
    user,
    deal_id: int,
    supplier_id: int,
    item_ids: list[int],
    *,
    note: str = "",
    to_email: str = "",
    partner_names: Optional[dict[int, dict]] = None,
) -> dict:
    """Предпросмотр запроса цены ровно в том виде, в каком он уйдёт партнёру: тема, строки (название партнёру, откуда оно,
    слова клиента — только сотруднику, чтобы поправить), заметка текстом и адрес. Ничего не отправляет и не пишет."""
    require_supply(user)
    if not item_ids:
        raise StockError("LINES_REQUIRED", 400)
    if len(item_ids) > MAX_LINES:
        raise StockError("TOO_MANY_LINES", 400)
    _deal, items = _deal_and_items(deal_id, item_ids)
    supplier = _preview_supplier(supplier_id)
    rows = partner_lines(items, partner_names)
    ready = all(row["name"] is not None for row in rows)
    first = next((row["name"] for row in rows if row["name"]), "") or "…"
    return {
        "subject": f"Запрос цены и срока поставки — {_summary(first, len(rows) - 1)}",
        "supplier": {"id": supplier.pk, "name": supplier.name},
        "to_email": (to_email or "").strip() or supplier_email(supplier) or "",
        "note": (note or "").strip()[:1000] or None,
        "ready": ready,
        "lines": [
            {
                "quote_item_id": row["item"].pk,
                "name": row["name"],
                "article": row["article"],
                "source": row["source"],
                "client_name": row["client_name"],
                "quantity": row["item"].quantity,
                "unit": row["item"].unit,
            }
            for row in rows
        ],
    }


def _summary(name: str, rest: int) -> str:
    """«Рельс Р65 и ещё 2 позиции»: имя первой позиции (до 80 знаков) и сколько ещё, со склонением."""
    name = name.strip()
    if len(name) > 80:
        name = name[:79].rstrip() + "…"
    if rest <= 0:
        return name
    tail = rest % 100
    word = (
        "позиций"
        if 11 <= tail <= 14
        else {1: "позиция", 2: "позиции", 3: "позиции", 4: "позиции"}.get(rest % 10, "позиций")
    )
    return f"{name} и ещё {rest} {word}"


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
        "supplier_order_id": request.supplier_order_id,
        "supplier_order_number": request.supplier_order.number if request.supplier_order_id else None,
        "requested_at": request.requested_at.isoformat(),
        "requested_by_name": person_name(request.requested_by) if request.requested_by_id else None,
        "requested_by": person_ref(request.requested_by) if request.requested_by_id else None,
        "to_email": request.to_email,
        "subject": request.subject,
        "note": request.note or None,
        "status": request.status,
        "error": request.error or None,
        "answered_at": request.answered_at.isoformat() if request.answered_at else None,
        "answered_by_name": person_name(request.answered_by) if request.answered_by_id else None,
        "answered_by": person_ref(request.answered_by) if request.answered_by_id else None,
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
    qs = PriceRequest.objects.select_related(
        "supplier", "deal", "supplier_order", "requested_by__crm_user_mapping", "answered_by__crm_user_mapping"
    ).prefetch_related("lines")
    if deal_id:
        qs = qs.filter(deal_id=deal_id)
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    return [present(r) for r in qs[:MAX_ROWS]]
