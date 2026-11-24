"""Запрос цены и заказ поставщику глазами партнёра (ДК-5, ADR-0030): проекция для ссылки и PDF письма.

Одна проекция на гостя по личной ссылке, на письмо и на PDF: только то, что партнёр вправе знать, — наш бренд, его
позиции, количество, его же цены, срок и комментарий партнёру. Клиента заявки, номера проекта, нашей цены продажи, наценки
и внутренних заметок здесь нет и быть не может: поля берутся из строк запроса и заказа поставщику, а не из заявки.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from typing import Any, Optional

from django.template.loader import render_to_string
from django.utils import timezone, translation

from core.tenant import own_company_id


def buyer_company():
    """Наша компания — «от кого» запрос и заказ; настроена не может не быть, иначе подпись пустая."""
    from parties.models import Company

    pk = own_company_id()
    return Company.objects.filter(pk=pk).first() if pk else None


def buyer_name() -> str:
    company = buyer_company()
    return company.name if company is not None else ""


def _qty(value: Any) -> str:
    from notifications.text_format import text_qty

    return text_qty(value)


def order_lines(order) -> list[dict]:
    """Строки заказа для партнёра: название, артикул, количество и цена поставщика; проект и КП клиента не называются."""
    rows = []
    for line in order.lines.all():
        price = line.unit_price
        rows.append(
            {
                "id": line.pk,
                "position": line.position,
                "name": line.name,
                "article": line.article or "",
                "unit": line.unit or "",
                "quantity": _qty(line.quantity),
                "unit_price": price,
                "total": (price * line.quantity) if price is not None else None,
            }
        )
    return rows


def order_total(order) -> Decimal:
    return sum(((line.unit_price or Decimal("0")) * line.quantity for line in order.lines.all()), Decimal("0"))


def request_lines(req) -> list[dict]:
    rows = []
    for line in req.lines.all():
        rows.append(
            {
                "id": line.pk,
                "position": len(rows) + 1,
                "name": line.name,
                "article": line.article or "",
                "unit": line.unit or "",
                "quantity": _qty(line.quantity),
                "unit_price": line.answer_price,
                "total": None,
                "lead_days": line.answer_lead_days,
            }
        )
    return rows


# ── PDF ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def _render(context: dict, language: Optional[str]) -> bytes:
    from weasyprint import HTML

    with translation.override(language or "ru"):
        html = render_to_string("supply/partner_document_pdf.html", context)
    buf = BytesIO()
    HTML(string=html).write_pdf(buf)
    return buf.getvalue()


def _lines_for_pdf(rows: list[dict]) -> list[dict]:
    from crm.templatetags.document_format import money

    return [
        {
            **row,
            "unit_price_text": money(row["unit_price"]) if row.get("unit_price") is not None else "",
            "total_text": money(row["total"]) if row.get("total") is not None else "",
        }
        for row in rows
    ]


def order_pdf(order) -> bytes:
    from crm.templatetags.document_format import money
    from notifications.text_format import text_date

    code = order.currency.code if order.currency_id else ""
    return _render(
        {
            "kind": "supplier_order",
            "number": order.number,
            "buyer": buyer_name(),
            "supplier": order.supplier.name,
            "date": text_date(order.sent_at or order.created_at),
            "expected_date": text_date(order.expected_date),
            "note": order.partner_note,
            "lines": _lines_for_pdf(order_lines(order)),
            "total": money(order_total(order), code) if code else money(order_total(order)),
        },
        order.supplier.language,
    )


def price_request_pdf(req) -> bytes:
    from notifications.text_format import text_date

    return _render(
        {
            "kind": "price_request",
            "number": request_reference(req),
            "buyer": buyer_name(),
            "supplier": req.supplier.name,
            "date": text_date(req.requested_at),
            "note": req.note,
            "lines": _lines_for_pdf(request_lines(req)),
        },
        req.supplier.language,
    )


def request_reference(req) -> str:
    """Что запрашиваем — часть темы после «—» («Рельс Р65 и ещё 2 позиции»): номера нашего проекта партнёру не называем."""
    ref = (req.subject or "").rsplit(" — ", 1)[-1].strip()
    return ref[:100] or f"RFQ-{req.pk}"


def now_date():
    return timezone.localdate()
