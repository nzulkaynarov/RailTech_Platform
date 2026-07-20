"""Shared document-rendering helpers — the seller branding pipeline for every PDF.

One place resolves the branding bundle (issuing company + its CompanyDocumentProfile +
logo URL) that every seller-issued document PDF (КП / договор / инвойс / акт) extends the
shared base template `crm/templates/crm/_document_base.html` with. Keeping the four builders
on an identical context shape is what makes the documents read as one product (ADR-0006
document-polish P1). Rule 8: logic lives here; the render functions are thin.
"""

from typing import Optional

from core.validators import is_hex_color

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


def public_quote_url(quote) -> Optional[str]:
    """Public no-login КП link built from the minted `public_access_token`, or None before send.
    ONE place owns the URL pattern (Rule 8) — shared by the send-email task and the PDF «Принять
    онлайн» CTA. Returns None when the token is unset (draft/preview → the CTA stays hidden)."""
    from django.conf import settings

    token = getattr(quote, "public_access_token", None)
    if not token:
        return None
    return f"{settings.FRONTEND_URL}/api/v1/public/quotes/{token}/"


def public_quote_qr(quote) -> Optional[str]:
    """SVG QR data-URI for the public «Принять онлайн» link (F-09), or None before send.

    Reuses public_quote_url so ONE place owns the URL pattern (Rule 8). SVG (not PNG) so the
    code stays crisp at any print size with no PIL rasterization, and it is embedded as a
    base64 `data:` URI because WeasyPrint fetches no network/CSP-blocked resources — it reads
    only inline/`data:` sources. Any failure degrades to None (the text-link CTA still renders),
    never a 500 in the off-thread PDF task.
    """
    url = public_quote_url(quote)
    if not url:
        return None
    try:
        import base64
        import io

        import qrcode
        import qrcode.image.svg as qrsvg

        image = qrcode.make(url, image_factory=qrsvg.SvgPathImage, box_size=11, border=2)
        buffer = io.BytesIO()
        image.save(buffer)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"
    except (ValueError, OSError, ImportError):
        return None


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
            "display_type": "ITEM",
            "line_no": 1,
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
            "display_type": "ITEM",
            "line_no": 2,
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
        "optional_items": [],
        "company": sample_buyer,
        **document_brand_context(company, is_demo=False),
    }
    return render_to_string("crm/quote_pdf.html", context)


def client_projection_items(quote) -> list:
    """Client-facing КП rows (Odoo `display_type`) in explicit `position` order, with document-level
    charges distributed proportionally into each priced line's delivered price.

    The list mixes three row kinds (each dict carries `display_type`):
      • ITEM    — a priced line: ONE all-in delivered price (charges spread in). NEVER a separate
                  «Доп. расходы» line — the goods-vs-charges breakout would let the buyer decompose
                  the seller's cost/charge structure (confidentiality).
      • SECTION — a group header (`section_subtotal` = Σ of that section's ITEM line totals, up to
                  the next SECTION). `line_total` is 0 so Σ line_total stays penny-exact.
      • NOTE    — a free-text note (`line_total` 0, no price).
    OPTIONAL lines are excluded here (they are quoted outside the totals — see
    `client_optional_items`). The charge remainder lands on the LAST priced line so the ITEM rows
    sum EXACTLY to quote.total_excl_vat (= subtotal + charges), the pre-VAT base the document taxes.
    """
    from decimal import ROUND_HALF_UP, Decimal

    from crm.models import QuoteItem

    penny = Decimal("0.01")
    items = list(quote.items.select_related("product", "frozen_currency").all())  # position order
    subtotal = quote.subtotal_excl_vat or Decimal("0")
    charges = quote.charges_total or Decimal("0")

    # Priced lines the charges distribute across = non-optional ITEM rows only. Sections/notes and
    # optional lines carry no share (sections/notes have no price; optional lines are off-total).
    priced = [it for it in items if it.display_type == QuoteItem.DisplayType.ITEM and not it.is_optional]
    projected_line_total: dict = {}
    projected_unit: dict = {}
    allocated = Decimal("0")
    last = len(priced) - 1
    for idx, item in enumerate(priced):
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
        projected_line_total[item.id] = line_total
        projected_unit[item.id] = (line_total / qty).quantize(penny, rounding=ROUND_HALF_UP) if qty else line_total

    rows: list = []
    line_no = 0  # 1-based sequence over PRICED rows only — sections/notes are not numbered.
    for item in items:
        # Optional priced lines are rendered in their own block, not in the main list.
        if item.display_type == QuoteItem.DisplayType.ITEM and item.is_optional:
            continue
        if item.display_type == QuoteItem.DisplayType.SECTION:
            rows.append(
                {
                    "display_type": "SECTION",
                    "imported_raw_name": item.imported_raw_name,
                    "line_total": Decimal("0"),
                    "section_subtotal": Decimal("0"),
                }
            )
        elif item.display_type == QuoteItem.DisplayType.NOTE:
            rows.append(
                {
                    "display_type": "NOTE",
                    "imported_raw_name": item.imported_raw_name,
                    "line_total": Decimal("0"),
                }
            )
        else:
            line_no += 1
            rows.append(
                {
                    "display_type": "ITEM",
                    "line_no": line_no,
                    "product": item.product,
                    "imported_raw_name": item.imported_raw_name,
                    "mpn": item.mpn,
                    "gost_drawing": item.gost_drawing,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "lead_time_days": item.lead_time_days,
                    "final_price_excl_vat": projected_unit.get(item.id, Decimal("0")),
                    "line_total": projected_line_total.get(item.id, Decimal("0")),
                }
            )

    # Second pass: each SECTION's subtotal = Σ line_total of the ITEM rows below it until the next
    # SECTION (its group). Ungrouped ITEM rows above the first SECTION are simply not summed.
    current_section = None
    for row in rows:
        if row["display_type"] == "SECTION":
            current_section = row
        elif row["display_type"] == "ITEM" and current_section is not None:
            current_section["section_subtotal"] += row["line_total"]
    return rows


def client_optional_items(quote) -> list:
    """Optional КП lines (is_optional ITEM rows) in `position` order — shown to the buyer with a
    price in a SEPARATE «Опционально» block, but NEVER folded into subtotal/НДС/total. No document
    charges are distributed into them (they are outside the priced offer); the raw per-line price
    and line total are shown as computed by the engine."""
    from crm.models import QuoteItem

    return [
        {
            "product": item.product,
            "imported_raw_name": item.imported_raw_name,
            "mpn": item.mpn,
            "gost_drawing": item.gost_drawing,
            "quantity": item.quantity,
            "unit": item.unit,
            "lead_time_days": item.lead_time_days,
            "final_price_excl_vat": item.final_price_excl_vat,
            "line_total": item.line_total,
        }
        for item in quote.items.select_related("product", "frozen_currency").all()
        if item.display_type == QuoteItem.DisplayType.ITEM and item.is_optional
    ]


def document_brand_context(seller_company, *, is_demo: bool = False) -> dict:
    """The branding bundle every concrete document template feeds the base with. Resolves the
    seller's CompanyDocumentProfile + logo. Safe when `seller_company` is None (renders the
    neutral platform fallback — never fake counterparty data)."""
    from accounts.models import CompanyDocumentProfile

    from .quotes import _profile_has_branding

    # ONE read of the profile row (never creates). Branding (legal name / logo / requisites) only
    # renders when actually filled (_profile_has_branding) → the template falls back to the Company
    # otherwise. The layout TOGGLES read from the raw row regardless, so a seller can flip «скрыть
    # колонку срока» without also filling their legal name.
    row = CompanyDocumentProfile.objects.filter(company=seller_company).first() if seller_company else None

    if row and getattr(row, "use_company_defaults", False) and seller_company:
        # Single source of truth (#287): with use_company_defaults ON the Company is authoritative
        # — its values OVERRIDE the profile row so a stale name/ИНН in the profile can never shadow
        # the live company data. Fall back to the profile value only where the Company field is
        # blank (so we never wipe a manual entry with an empty company field). This block mutates
        # the in-memory row only (never .save()) — it just feeds the render.
        row.legal_name = seller_company.name or row.legal_name
        row.inn = seller_company.inn or row.inn
        row.legal_address = seller_company.legal_address or row.legal_address
        if seller_company.logo:
            row.logo = seller_company.logo
        bank_parts = []
        if seller_company.bank_account:
            bank_parts.append(f"р/с: {seller_company.bank_account}")
        if seller_company.mfo:
            bank_parts.append(f"МФО: {seller_company.mfo}")
        if bank_parts:
            row.bank_details = ", ".join(bank_parts)
        if seller_company.contact_person:
            row.signatory_name = seller_company.contact_person

    branded = row if _profile_has_branding(row) else None
    # SEC (audit #9): accent goes raw into a <style> block, so neutralize anything that
    # isn't a #hex colour at render time too — defence-in-depth for any historical row
    # written before update_document_profile validated it (belt-and-suspenders vs CSS
    # injection → WeasyPrint SSRF).
    raw_accent = getattr(branded, "accent_color", None) if branded else None
    accent = raw_accent if is_hex_color(raw_accent) else _DEFAULT_ACCENT
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
