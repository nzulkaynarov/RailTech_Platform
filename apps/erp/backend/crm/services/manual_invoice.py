"""Manual invoice «from scratch» (G2) — a DRAFT invoice on a deal WITHOUT a signed contract.

Product benchmark: Odoo / МойСклад let a seller raise an invoice directly from an order/quotation,
skipping the contract step (СНГ «счёт = оферта» — the счёт itself is the offer). Here the seller
bills a buyer from an active КП on the deal (``source_quote_id``) and/or an ad-hoc manual line list.
``Invoice.contract`` is already nullable, so NO schema change is needed.

The invoice is BORN a DRAFT (``contract=None``) and then rides the EXISTING DRAFT → «Выставить» /
«Отменить» lifecycle (``invoice_lifecycle.issue_invoice`` / ``cancel_invoice``) unchanged.

Money discipline (avoids the B1 cost-currency bug): amounts and currency follow the PRESENTATION
currency (``Quote.quote_currency``, UZS by business rule) — never a line's frozen COST currency.
When no source КП is given the currency is left NULL, and the PDF/serializer fall back to UZS, the
engine's canonical currency.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Tuple

from django.db import transaction

from core.currency import line_amount
from core.quantity import to_qty

from ..constants import DEFAULT_INVOICE_DUE_DAYS, InvoiceStatusCode
from ..models import ActivityLog

_PENNY = Decimal("0.01")


def _seller_gate_for_deal(actor, deal_id) -> Optional[str]:
    """Seller-side gate for creating a manual invoice on a deal (no invoice exists yet, so the
    invoice-scoped ``_assert_seller_may_act_on_invoice`` can't be reused): own-company staff.
    Returns an error code or None."""
    from accounts.services import is_seller

    if not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return "MEMBER_REQUIRED_FOR_ACTION"
    return None


def _clean_manual_lines(lines) -> Tuple[Optional[list], Optional[str]]:
    """Validate the manual line list into ``[(description, quantity, unit_price_excl_vat, product_id), ...]``.
    Amounts are read as the КП PRESENTATION currency (never a cost currency). A line names a catalog card
    (``product_id``) or a text; a text-only line gets its card later (``_resolve_cards``, ADR-0027 п. 1)."""
    cleaned = []
    for raw in lines or []:
        description = (str(raw.get("description") or "")).strip()
        try:
            product_id = int(raw["product_id"]) if raw.get("product_id") not in (None, "") else None
            quantity = to_qty(raw.get("quantity") or 0)
            unit_price = Decimal(str(raw.get("unit_price_excl_vat") or "0"))
        except (ValueError, ArithmeticError, TypeError):
            return None, "INVOICE_LINE_INVALID"
        if not description and product_id is None:
            return None, "INVOICE_LINE_DESCRIPTION_REQUIRED"
        if quantity <= 0 or unit_price < 0:
            return None, "INVOICE_LINE_INVALID"
        cleaned.append((description, quantity, unit_price, product_id))
    return cleaned, None


def _resolve_cards(manual_lines, deal) -> Tuple[Optional[list], Optional[str]]:
    """Every manual line gets a catalog card (ADR-0027 п. 1): the named one, or a found/new draft by its text.

    A named card must be a live card of our catalog (not archived). Returns
    ``[(description, quantity, unit_price, product), ...]`` or an error code."""
    from catalog.candidates import card_for_text
    from catalog.models import Product

    ids = {pid for *_rest, pid in manual_lines if pid is not None}
    cards = {p.pk: p for p in Product.objects.filter(pk__in=ids).exclude(status__code="ARCHIVED").select_related("uom")}
    resolved = []
    for description, quantity, unit_price, product_id in manual_lines:
        if product_id is not None:
            product = cards.get(product_id)
            if product is None:
                return None, "INVOICE_LINE_PRODUCT_INVALID"
        else:
            product = card_for_text(description, deal=deal)
        name = description or (product.name if product is not None else "")
        resolved.append((name, quantity, unit_price, product))
    return resolved, None


def _unit_of(product) -> Tuple[str, str]:
    """Единица строки — единица карточки по умолчанию (ADR-0027 п. 10)."""
    uom = getattr(product, "uom", None) if product is not None else None
    return (uom.name[:32], uom.code) if uom is not None else ("", "")


@transaction.atomic
def create_manual_invoice(
    deal_id: int,
    actor,
    *,
    source_quote_id: Optional[int] = None,
    lines: Optional[list] = None,
    due_days: int = DEFAULT_INVOICE_DUE_DAYS,
) -> Tuple[Optional[object], Optional[str]]:
    """Create a DRAFT invoice on ``deal_id`` with ``contract=None``.

    Populates lines from an active КП on the deal (``source_quote_id`` → the SAME billable
    projection the contract→invoice path uses) and/or an explicit manual line list. Requires at
    least one source. Returns ``(invoice, None)`` or ``(None, error_code)``.
    """
    from datetime import timedelta

    from django.utils import timezone

    from core.tenant import own_company_id

    from ..models import Deal, Invoice, InvoiceItem, Quote
    from .billing import _istatus, _next_invoice_number

    if gate_err := _seller_gate_for_deal(actor, deal_id):
        return None, gate_err

    try:
        deal = Deal.objects.get(pk=deal_id)
    except Deal.DoesNotExist:
        return None, "NOT_FOUND"

    manual_lines, line_err = _clean_manual_lines(lines)
    if line_err:
        return None, line_err

    source_quote = None
    if source_quote_id:
        source_quote = (
            Quote.objects.select_related("quote_currency").prefetch_related("items").filter(pk=source_quote_id).first()
        )
        if source_quote is None:
            return None, "NOT_FOUND"
        # The КП must belong to THIS deal (a seller can't pull a foreign deal's КП onto this
        # invoice).
        if source_quote.deal_id != deal.id:
            return None, "QUOTE_DEAL_MISMATCH"

    if source_quote is None and not manual_lines:
        return None, "INVOICE_NO_LINES"

    manual_lines, card_err = _resolve_cards(manual_lines, deal)
    if card_err:
        return None, card_err

    # Presentation currency = the КП's quote_currency (UZS by rule); NULL for a pure-manual счёт
    # (PDF/serializer fall back to UZS). NEVER a line's frozen COST currency (the B1 bug).
    currency = source_quote.quote_currency if source_quote else None
    vat_rate = (source_quote.vat_rate if source_quote else Decimal("0")) / Decimal("100")

    # Seller company = the own company (the seller of every deal) → its number prefix + counter.
    seller_company_id = own_company_id()
    from accounts.models import Company

    seller_company = Company.objects.filter(pk=seller_company_id).first() if seller_company_id else None

    subtotal = Decimal("0")
    vat_amount = Decimal("0")
    total = Decimal("0")
    item_specs = []  # (description, quantity, unit_price, product, unit, unit_code, source_quote_item, line_total)

    if source_quote is not None:
        # Mirror the contract→invoice projection EXACTLY: the header totals come verbatim from the
        # КП header (which the engine computes in the presentation currency, INCLUDING document
        # charges in total_incl_vat), and the InvoiceItems are ONLY the billable lines (SECTION/
        # NOTE and optional ITEMs are excluded — same .billable() filter, so Σ lines = subtotal).
        subtotal += source_quote.total_excl_vat
        vat_amount += source_quote.vat_amount or Decimal("0")
        total += source_quote.total_incl_vat or Decimal("0")
        from catalog.candidates import link_quote_lines

        link_quote_lines(source_quote)  # строки КП до перехода получают карточку (ADR-0027 п. 1), идемпотентно
        from .documents.projection import client_billable_lines

        for qi in client_billable_lines(source_quote):
            item_specs.append(
                (
                    (qi.product.name if qi.product else qi.imported_raw_name) or "Позиция",
                    qi.quantity,
                    qi.final_price_excl_vat,
                    qi.product,
                    qi.unit,
                    qi.unit_code,
                    qi._item,
                    qi.line_total,  # projected: Σ lines = quote.total_excl_vat penny-exact
                )
            )

    for description, quantity, unit_price, product in manual_lines:
        line_total = line_amount(unit_price, quantity)
        line_vat = (line_total * vat_rate).quantize(_PENNY, rounding=ROUND_HALF_UP)
        subtotal += line_total
        vat_amount += line_vat
        total += line_total + line_vat
        item_specs.append((description, quantity, unit_price, product, *_unit_of(product), None, line_total))

    invoice = Invoice.objects.create(
        deal=deal,
        contract=None,
        number=_next_invoice_number(seller_company),
        status=_istatus(InvoiceStatusCode.DRAFT),
        issued_at=None,
        due_date=(timezone.now() + timedelta(days=due_days)).date(),
        subtotal_excl_vat=subtotal.quantize(_PENNY, rounding=ROUND_HALF_UP),
        vat_amount=vat_amount.quantize(_PENNY, rounding=ROUND_HALF_UP),
        total_incl_vat=total.quantize(_PENNY, rounding=ROUND_HALF_UP),
        currency=currency,
        created_by=actor,
    )
    InvoiceItem.objects.bulk_create(
        [
            InvoiceItem(
                invoice=invoice,
                description=description,
                product=product,
                quantity=quantity,
                unit=unit,
                unit_code=unit_code,
                unit_price_excl_vat=unit_price,
                line_total_excl_vat=spec_line_total,
                source_quote_item=source_quote_item,
            )
            for description, quantity, unit_price, product, unit, unit_code, source_quote_item, spec_line_total in item_specs
        ]
    )

    ActivityLog.objects.create(
        action="Счёт создан вручную (черновик)",
        detail=f"Счёт {invoice.number} по сделке #{invoice.deal_id} (без договора)",
        event_code="invoice.created_manual",
        event_params={"number": invoice.number, "deal_id": invoice.deal_id, "source_quote_id": source_quote_id},
        user=actor,
        level="INFO",
        deal=invoice.deal,
        company_id=invoice.deal.company_id,
    )
    return invoice, None
