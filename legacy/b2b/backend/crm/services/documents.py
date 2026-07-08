"""Shared document-rendering helpers — the seller branding pipeline for every PDF.

One place resolves the branding bundle (issuing company + its CompanyDocumentProfile +
logo URL) that every seller-issued document PDF (КП / договор / инвойс / акт) extends the
shared base template `crm/templates/crm/_document_base.html` with. Keeping the four builders
on an identical context shape is what makes the documents read as one product (ADR-0006
document-polish P1). Rule 8: logic lives here; the render functions are thin.
"""

from typing import Optional

_DEFAULT_ACCENT = "#15294d"
_DARK_INK = "#1b1f27"
_LIGHT_INK = "#ffffff"


def accent_contrast(accent_hex: Optional[str]) -> str:
    """Readable text color to place ON the accent fill (table head / ИТОГО row). WeasyPrint can't
    compute contrast, so we pick it here: dark ink on a light brand accent, white on a dark one.
    Uses the WCAG relative-luminance threshold; malformed/short hex falls back to white."""
    value = (accent_hex or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return _LIGHT_INK
    try:
        red, green, blue = (int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        return _LIGHT_INK

    def _linear(channel):
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)
    return _DARK_INK if luminance > 0.45 else _LIGHT_INK


def seller_logo_url(seller_profile) -> Optional[str]:
    """The seller's logo URL, or None when unset / the storage backend can't resolve it."""
    if not seller_profile or not seller_profile.logo:
        return None
    try:
        return seller_profile.logo.url
    except (ValueError, OSError):  # storage backend unavailable / missing key
        return None


def render_document_profile_preview_html(company) -> str:
    """Render a SAMPLE КП as HTML using the company's CURRENT document profile — the live preview
    behind the document-settings panel (P3). Uses representative sample data (never a real quote),
    so the seller sees exactly how their branding + layout toggles look before issuing a real
    offer. Returns HTML (not a PDF): instant, cheap to re-render on every change, and it never
    runs WeasyPrint in the request thread (ARCH-03). It IS the same template the PDF renders."""
    from datetime import date
    from decimal import Decimal

    from django.template.loader import render_to_string

    sample_items = [
        {
            "product": None,
            "imported_raw_name": "Подшипник буксовый ЦКБ тип 2726",
            "mpn": "2726",
            "gost_drawing": "ГОСТ 24955-81",
            "quantity": 10,
            "unit": "шт.",
            "lead_time_days": 21,
            "final_price_excl_vat": Decimal("1500000.00"),
            "line_total": Decimal("15000000.00"),
        },
        {
            "product": None,
            "imported_raw_name": "Колодка тормозная композиционная",
            "mpn": "",
            "gost_drawing": "",
            "quantity": 40,
            "unit": "шт.",
            "lead_time_days": None,
            "final_price_excl_vat": Decimal("85000.00"),
            "line_total": Decimal("3400000.00"),
        },
    ]
    sample_quote = {
        "quote_currency": {"code": "UZS"},
        "number": "КП-2026-000123 (образец)",
        "deal_id": 0,
        "version": 1,
        "created_at": date(2026, 7, 8),
        "valid_until": date(2026, 8, 8),
        "subtotal_excl_vat": Decimal("18400000.00"),
        "charges_total": Decimal("0"),
        "total_excl_vat": Decimal("18400000.00"),
        "vat_rate": Decimal("12"),
        "vat_amount": Decimal("2208000.00"),
        "total_incl_vat": Decimal("20608000.00"),
        "effective_delivery_lead_time_days": 21,
        "delivery_basis": {"code": "DAP", "name": "Ташкент"},
        "delivery_note": "",
        "notes": "Образец документа для предпросмотра настроек.",
        "fx_snapshot": {"USD": "12650.00"},
        "frozen_at": None,
        "updated_at": date(2026, 7, 8),
    }
    sample_buyer = {
        "name": "ООО «Образец-Клиент»",
        "inn": "300000000",
        "legal_address": "г. Ташкент, ул. Примерная, 1",
        "contact_person": "",
    }
    context = {
        "quote": sample_quote,
        "items": sample_items,
        "company": sample_buyer,
        **document_brand_context(company, is_demo=False),
    }
    return render_to_string("crm/quote_pdf.html", context)


def client_projection_items(quote) -> list:
    """Client-facing КП lines with document-level charges distributed proportionally into each
    line's delivered price.

    Confidentiality: the buyer sees ONE all-in price per line, never a separate «Доп. расходы»
    line — breaking goods vs charges apart lets the buyer decompose the seller's cost/charge
    structure on a competitive offer. The charges (freight/handling/…) are spread across the lines
    in proportion to line value; the rounding remainder lands on the LAST line so the lines sum
    EXACTLY to quote.total_excl_vat (= subtotal + charges), the pre-VAT base the document taxes.
    """
    from decimal import ROUND_HALF_UP, Decimal

    penny = Decimal("0.01")
    items = list(quote.items.select_related("product", "frozen_currency").all())
    subtotal = quote.subtotal_excl_vat or Decimal("0")
    charges = quote.charges_total or Decimal("0")
    projected = []
    allocated = Decimal("0")
    last = len(items) - 1
    for idx, item in enumerate(items):
        base = item.line_total or Decimal("0")
        if charges and subtotal:
            if idx < last:
                share = (charges * base / subtotal).quantize(penny, rounding=ROUND_HALF_UP)
                allocated += share
            else:
                share = charges - allocated  # last line absorbs the remainder → penny-exact Σ
        else:
            share = Decimal("0")
        line_total = base + share
        qty = item.quantity or Decimal("1")
        unit = (line_total / qty).quantize(penny, rounding=ROUND_HALF_UP) if qty else line_total
        projected.append(
            {
                "product": item.product,
                "imported_raw_name": item.imported_raw_name,
                "mpn": item.mpn,
                "gost_drawing": item.gost_drawing,
                "quantity": item.quantity,
                "unit": item.unit,
                "lead_time_days": item.lead_time_days,
                "final_price_excl_vat": unit,
                "line_total": line_total,
            }
        )
    return projected


def document_brand_context(seller_company, *, is_demo: bool = False) -> dict:
    """The branding bundle every concrete document template feeds the base with. Resolves the
    seller's CompanyDocumentProfile + logo. Safe when `seller_company` is None (renders the
    neutral platform fallback — never fake counterparty data)."""
    from .quotes import _seller_document_profile

    from accounts.models import CompanyDocumentProfile

    from .quotes import _profile_has_branding

    # ONE read of the profile row (never creates). Branding (legal name / logo / requisites) only
    # renders when actually filled (_profile_has_branding) → the template falls back to the Company
    # otherwise. The layout TOGGLES read from the raw row regardless, so a seller can flip «скрыть
    # колонку срока» without also filling their legal name.
    row = CompanyDocumentProfile.objects.filter(company=seller_company).first() if seller_company else None
    branded = row if _profile_has_branding(row) else None
    accent = (getattr(branded, "accent_color", None) or _DEFAULT_ACCENT) if branded else _DEFAULT_ACCENT
    return {
        "seller": seller_company,
        "seller_profile": branded,
        "seller_logo_url": seller_logo_url(branded),
        "is_demo": is_demo,
        "show_logo": row.show_logo if row else True,
        "show_lead_time": row.show_lead_time if row else True,
        "show_fx_note": row.show_fx_note if row else False,
        # Full-theming inputs for _document_base.html (F-03): every accent surface reads --accent,
        # and text on the accent fill reads --accent-contrast so a light brand accent stays legible.
        "accent": accent,
        "accent_contrast": accent_contrast(accent),
    }
