"""Shared document-rendering helpers — the seller branding pipeline for every PDF.

One place resolves the branding bundle (issuing company + its CompanyDocumentProfile +
logo URL) that every seller-issued document PDF (КП / договор / инвойс / акт) extends the
shared base template `crm/templates/crm/_document_base.html` with. Keeping the four builders
on an identical context shape is what makes the documents read as one product (ADR-0006
document-polish P1). Rule 8: logic lives here; the render functions are thin.
"""

from typing import Optional


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
    return {
        "seller": seller_company,
        "seller_profile": branded,
        "seller_logo_url": seller_logo_url(branded),
        "is_demo": is_demo,
        "show_logo": row.show_logo if row else True,
        "show_lead_time": row.show_lead_time if row else True,
        "show_fx_note": row.show_fx_note if row else False,
    }
