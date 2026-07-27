"""Shared document-rendering helpers — the seller branding pipeline for every PDF.

One place resolves the branding bundle (issuing company + its CompanyDocumentProfile +
logo URL) that every seller-issued document PDF (КП / договор / инвойс / акт) extends the
shared base template `crm/templates/crm/_document_base.html` with. Keeping the four builders
on an identical context shape is what makes the documents read as one product (ADR-0006
document-polish P1). Rule 8: logic lives here; the render functions are thin.
"""

import re
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


# Logos above this size are dropped from the PDF render rather than inlined (a data: URI of a
# multi-MB upload would bloat every render); the letterhead then falls back to the text name.
_LOGO_EMBED_MAX_BYTES = 1_000_000


def brand_context_for_pdf(brand: dict) -> dict:
    """Prepare a brand context for a WeasyPrint render: inline the seller logo as a data: URI.

    On prod (FileSystemStorage) ``seller_logo_url`` is a RELATIVE ``/media/…`` URL — WeasyPrint
    renders from ``HTML(string=…)`` with no ``base_url`` and deliberately no network fetching, so
    the logo came out as a broken-image box on every prod PDF. Browser surfaces (public pages,
    settings iframe, SPA) resolve the same URL fine, so the swap happens ONLY at PDF render time —
    never in the stored brand_snapshot or serializer slices (a data: URI there would bloat every
    row). Absolute http(s) URLs (e.g. dev MinIO, reachable in-network) are left as-is; missing or
    oversized files degrade to no logo (the template then prints the text name, not a broken box).
    """
    import base64
    import mimetypes

    from django.conf import settings

    logo_url = brand.get("seller_logo_url")
    if not logo_url or logo_url.startswith("data:"):
        return brand

    data = None
    name = ""
    # Live render context carries the real CompanyDocumentProfile — read its file straight from
    # storage (works for ANY backend/URL shape: prod relative /media, dev MinIO absolute URL that
    # the container can't reach back through, future CDN). Snapshot renders carry a
    # SimpleNamespace without the FieldFile — those fall to the MEDIA_URL-relative branch below.
    profile = brand.get("seller_profile")
    logo_field = getattr(profile, "logo", None)
    if logo_field is not None and hasattr(logo_field, "open"):
        try:
            with logo_field.open("rb") as file_handle:
                data = file_handle.read(_LOGO_EMBED_MAX_BYTES + 1)
            name = logo_field.name or ""
        except (OSError, ValueError, FileNotFoundError):
            data = None
    if data is None and logo_url.startswith(settings.MEDIA_URL):
        from django.core.files.storage import default_storage

        name = logo_url[len(settings.MEDIA_URL):]
        try:
            with default_storage.open(name, "rb") as file_handle:
                data = file_handle.read(_LOGO_EMBED_MAX_BYTES + 1)
        except (OSError, ValueError, FileNotFoundError):
            data = None
    if data is None:
        # Unresolvable absolute URL (or dangling key): degrade to NO logo — the letterhead then
        # prints the text name, never a broken-image box (WeasyPrint deliberately fetches nothing).
        return {**brand, "seller_logo_url": None}
    if len(data) > _LOGO_EMBED_MAX_BYTES:
        return {**brand, "seller_logo_url": None}
    mime = mimetypes.guess_type(name)[0] or "image/png"
    encoded = base64.b64encode(data).decode("ascii")
    return {**brand, "seller_logo_url": f"data:{mime};base64,{encoded}"}


# The document kinds the Document-Layout preview can render (mirrors the real PDF set).
PREVIEW_DOC_TYPES = ("KP", "CT", "INV", "ACT", "DOC")

# Draft-override keys the theme editor may pass for a WYSIWYG preview of UNSAVED settings
# (applied to an in-memory row only — never saved; hex/choice values are neutralized by the
# render-time allowlists in _brand_context_from_row).
_PREVIEW_TEXT_OVERRIDES = (
    "legal_name",
    "inn",
    "legal_address",
    "bank_details",
    "signatory_name",
    "signatory_position",
    "footer_text",
    "accent_color",
    "secondary_color",
    "layout_preset",
    "font_family",
    "cover_letter_text",
)
_PREVIEW_BOOL_OVERRIDES = (
    "use_company_defaults",
    "show_logo",
    "show_lead_time",
    "show_fx_note",
    "show_cover_letter",
    "show_bank_in_header",
)


def render_document_profile_preview_html(company, doc_type: str = "KP", overrides: dict = None) -> str:
    """Render a SAMPLE document of the requested kind (КП / договор / инвойс / акт / письмо) as
    HTML using the company's document profile, optionally overlaid with UNSAVED draft settings —
    the live Document-Layout preview (Odoo wizard model: see the theme on every report BEFORE
    saving). Uses representative sample data (never a real document), returns HTML (not a PDF):
    instant, cheap to re-render on every change, never WeasyPrint in the request thread
    (ARCH-03). They ARE the same templates the PDFs render — the preview cannot drift."""
    from accounts.models import CompanyDocumentProfile

    row = CompanyDocumentProfile.objects.filter(company=company).first()
    if overrides:
        if row is None:
            row = CompanyDocumentProfile(company=company)  # in-memory only — never .save()
        for field in _PREVIEW_TEXT_OVERRIDES:
            if field in overrides:
                setattr(row, field, overrides[field] or "")
        for field in _PREVIEW_BOOL_OVERRIDES:
            if field in overrides:
                value = overrides[field]
                if isinstance(value, str):
                    value = value.strip().lower() in {"1", "true", "yes", "on"}
                setattr(row, field, bool(value))
    brand = _brand_context_from_row(company, row, is_demo=False)

    if doc_type == "CT":
        return _render_sample_contract_html(brand)
    if doc_type == "INV":
        return _render_sample_invoice_html(brand)
    if doc_type == "ACT":
        return _render_sample_act_html(brand)
    if doc_type == "DOC":
        return _render_sample_letter_html(brand)
    # `row` (draft profile) is passed so the cover-letter toggle/text preview live, even before
    # the seller has filled the branding requisites (cover is independent of _profile_has_branding).
    return _render_sample_quote_html(brand, cover_profile=row)


# Shared sample counterparty for every preview document (never real data — Rule 1 concerns
# PRODUCTION data paths; a clearly-labelled «образец» preview is the documented exception,
# same as the pre-existing sample КП below).
_SAMPLE_BUYER = {
    "name": "ООО «Образец-Клиент»",
    "inn": "300000000",
    "legal_address": "г. Ташкент, ул. Примерная, 1",
    "contact_person": "",
}


def _sample_invoice_lines():
    from decimal import Decimal

    return [
        {
            "description": "Подшипник буксовый ЦКБ тип 2726",
            "quantity": 10,
            "unit_price_excl_vat": Decimal("1500000.00"),
            "line_total_excl_vat": Decimal("15000000.00"),
        },
        {
            "description": "Колодка тормозная композиционная",
            "quantity": 40,
            "unit_price_excl_vat": Decimal("85000.00"),
            "line_total_excl_vat": Decimal("3400000.00"),
        },
    ]


def _render_sample_quote_html(brand: dict, cover_profile=None) -> str:
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
    # «Фирменный бланк» blocks in the preview (spec-kp-blank): cover letter resolved from the
    # (draft) profile so the seller sees it live; structured terms use representative sample values
    # (the preview is an «образец») + the shipment place from the branded requisites.
    # `seller_name` is composed in the template (firstof legal_name/name), not carried in the brand
    # dict — derive it here so the {{seller}} token resolves in the preview like it does live.
    _seller_name = (
        getattr(brand.get("seller_profile"), "legal_name", "")
        or getattr(brand.get("seller"), "name", "")
        or ""
    )
    cover_text = resolve_cover_letter(
        cover_profile, buyer_name=_SAMPLE_BUYER["name"], deal_ref="08.07.2026", seller_name=_seller_name
    )
    quote_terms = build_quote_terms(
        shipment_place=(getattr(brand.get("seller_profile"), "legal_address", "") or "Республика Узбекистан, г. Ташкент"),
        lead_days=21,
        payment="100% предоплата",
        incoterm="DAP (Ташкент)",
        warranty_months=12,
        valid_until="08.08.2026",
        other="При отсутствии модели у производителя может быть предложен аналог с соответствующими характеристиками.",
    )
    context = {
        "quote": sample_quote,
        "items": sample_items,
        "optional_items": [],
        "company": _SAMPLE_BUYER,
        "cover_text": cover_text,
        "quote_terms": quote_terms,
        # Shared 3-line VAT block (D1) — the preview mirrors the real render.
        "totals": document_totals(
            ccy="UZS",
            vat_rate=sample_quote["vat_rate"],
            subtotal=sample_quote["total_excl_vat"],
            vat_amount=sample_quote["vat_amount"],
            total=sample_quote["total_incl_vat"],
        ),
        # Branding preview, not a real export — no «ЧЕРНОВИК» watermark (it would obscure the very
        # branding this sample exists to show); keep the lead-time column visible so the seller can
        # see it styled when their profile toggle is on.
        "is_draft": False,
        "has_line_lead_time": True,
        **brand,
    }
    return render_to_string("crm/quote_pdf.html", context)


def _render_sample_contract_html(brand: dict) -> str:
    """Sample договор — the SAME contract_pdf.html the real contract renders."""
    from datetime import date
    from decimal import Decimal

    from django.template.loader import render_to_string

    sample_quote = {
        "quote_currency": {"code": "UZS"},
        "vat_rate": Decimal("12"),
        "effective_delivery_lead_time_days": 21,
        "delivery_basis": {"code": "DAP", "name": "Ташкент"},
    }
    sample_items = [
        {
            "product": None,
            "imported_raw_name": "Подшипник буксовый ЦКБ тип 2726",
            "quantity": 10,
            "unit": "шт.",
            "final_price_excl_vat": Decimal("1500000.00"),
            "line_total": Decimal("15000000.00"),
        },
        {
            "product": None,
            "imported_raw_name": "Колодка тормозная композиционная",
            "quantity": 40,
            "unit": "шт.",
            "final_price_excl_vat": Decimal("85000.00"),
            "line_total": Decimal("3400000.00"),
        },
    ]
    sample_contract = {
        "number": "CT-2026-00042 (образец)",
        "created_at": date(2026, 7, 8),
        "valid_from": date(2026, 7, 8),
        "valid_until": date(2026, 12, 31),
        "total_amount": Decimal("20608000.00"),
        "notes": "",
        "client_signed_at": None,
        "manager_signed_at": None,
        "client_signer": None,
        "manager_signer": None,
    }
    context = {
        "contract": sample_contract,
        "deal": {"id": 0},
        "company": _SAMPLE_BUYER,
        "quote": sample_quote,
        "items": sample_items,
        "totals": document_totals(ccy="UZS", vat_rate=Decimal("12"), total=Decimal("20608000.00")),
        **brand,
    }
    return render_to_string("crm/contract_pdf.html", context)


def _render_sample_invoice_html(brand: dict) -> str:
    """Sample инвойс — the SAME invoice_pdf.html the real invoice renders."""
    from datetime import date
    from decimal import Decimal

    from django.template.loader import render_to_string

    sample_invoice = {
        "number": "INV-2026-00042 (образец)",
        "issued_at": date(2026, 7, 8),
        "due_date": date(2026, 8, 8),
        "notes": "",
        "contract": {"number": "CT-2026-00042"},
        "subtotal_excl_vat": Decimal("18400000.00"),
        "vat_amount": Decimal("2208000.00"),
        "total_incl_vat": Decimal("20608000.00"),
        "amount_paid": Decimal("0"),
        "balance_due": Decimal("20608000.00"),
    }
    context = {
        "invoice": sample_invoice,
        "items": _sample_invoice_lines(),
        "company": _SAMPLE_BUYER,
        "totals": document_totals(
            ccy="UZS",
            subtotal=Decimal("18400000.00"),
            vat_amount=Decimal("2208000.00"),
            total=Decimal("20608000.00"),
            amount_paid=Decimal("0"),
            balance_due=Decimal("20608000.00"),
        ),
        **brand,
    }
    return render_to_string("crm/invoice_pdf.html", context)


def _render_sample_act_html(brand: dict) -> str:
    """Sample акт — the SAME act_pdf.html the real act renders."""
    from datetime import date
    from decimal import Decimal

    from django.template.loader import render_to_string

    sample_invoice = {
        "number": "INV-2026-00042",
        "issued_at": date(2026, 7, 8),
        "items": {"all": _sample_invoice_lines()},
    }
    sample_act = {
        "number": "ACT-2026-00042 (образец)",
        "issued_at": date(2026, 7, 15),
        "deal_id": 0,
        "total_amount": Decimal("20608000.00"),
        "contract": {"number": "CT-2026-00042", "created_at": date(2026, 7, 8)},
        "invoice": sample_invoice,
    }
    context = {
        "act": sample_act,
        "invoice": sample_invoice,
        "company": _SAMPLE_BUYER,
        # Act mirrors its invoice — the same net/VAT/gross split.
        "totals": document_totals(
            ccy="UZS",
            subtotal=Decimal("18400000.00"),
            vat_amount=Decimal("2208000.00"),
            total=Decimal("20608000.00"),
        ),
        **brand,
    }
    return render_to_string("crm/act_pdf.html", context)


def _render_sample_letter_html(brand: dict) -> str:
    """Sample произвольное письмо — the SAME generated_document_pdf.html the templater renders."""
    from datetime import date

    from django.template.loader import render_to_string

    sample_letter = {
        "title": "Гарантийное письмо (образец)",
        "number": "DOC-2026-00042",
        "created_at": date(2026, 7, 8),
        "rendered_html": (
            "<p>Настоящим гарантируем оплату по сделке #1024 в полном объёме в согласованные сроки.</p>"
            "<p>Сумма обязательств соответствует коммерческому предложению КП-2026-00042 "
            "на сумму 20 608 000 UZS.</p>"
        ),
    }
    context = {"document": sample_letter, **brand}
    return render_to_string("crm/generated_document_pdf.html", context)


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
    # SECTION (its group), plus a count of grouped ITEM rows so an EMPTY section can be dropped.
    # Ungrouped ITEM rows above the first SECTION are simply not summed.
    current_section = None
    for row in rows:
        if row["display_type"] == "SECTION":
            current_section = row
            row["_item_count"] = 0
        elif row["display_type"] == "ITEM" and current_section is not None:
            current_section["section_subtotal"] += row["line_total"]
            current_section["_item_count"] += 1

    # Wave C polish: a document should never show an EMPTY structural row. Drop a SECTION that
    # groups no ITEM lines (the «НОВЫЙ РАЗДЕЛ — 0,00» artifact) and a NOTE with no text — both
    # read as a rendering bug to the client. Count-based, NOT subtotal-based: a section whose real
    # lines sum to 0 (all free/included) still groups items and MUST render.
    def _keep(row) -> bool:
        if row["display_type"] == "SECTION":
            return row.get("_item_count", 0) > 0
        if row["display_type"] == "NOTE":
            return bool((row.get("imported_raw_name") or "").strip())
        return True

    return [row for row in rows if _keep(row)]


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


def public_quote_page_context(quote) -> dict:
    """Full render context for the public КП HTML page (Wave A) — the SAME client projection the
    PDF renders: `client_projection_items` / `client_optional_items` (charges distributed into
    per-line delivered prices, NO cost/margin/charges breakout) + the seller branding bundle.

    The page is the browser-facing twin of ``crm/quote_pdf.html``; keeping it on these shared
    helpers is what guarantees the two documents never diverge and the confidentiality invariant
    (no landed_cost / margin / FX / goods-vs-charges) holds identically on both surfaces.
    """
    from accounts.services.entitlements import quote_send_entitled
    from crm.services.quotes._shared import _quote_seller_company

    seller_company = _quote_seller_company(quote)
    projected_items = client_projection_items(quote)
    context = {
        "quote": quote,
        "items": projected_items,
        "optional_items": client_optional_items(quote),
        "company": quote.deal.company,
        # Offline client fallback for the «Покупатель» block (deal.company is NULL for a
        # seller-created deal with an offline contact).
        "contact": quote.deal.contact,
        # Mirror the PDF (#375): render the per-line «Срок» column only when at least one line
        # actually carries a lead time — otherwise it is a column of «—» duplicating the single
        # КП-level «Срок поставки» below.
        "has_line_lead_time": any(item.get("lead_time_days") for item in projected_items),
        "public_quote_url": public_quote_url(quote),
        # D1c: the online page is the PDF's twin — same cover letter, structured «Условия
        # поставки» and 3-line VAT totals (one shared builder), so the QR «оригинал» never
        # looks poorer than the attached PDF.
        **quote_document_extras(quote, seller_company),
        **document_brand_context(
            seller_company,
            is_demo=bool(seller_company) and not quote_send_entitled(seller_company.id),
        ),
    }
    return context


# Document theme (D2, Odoo Document Layout model). Font stacks are limited to families the
# backend container actually ships (DejaVu — full Cyrillic); offering a font WeasyPrint would
# silently substitute would be a fake choice (Rule 1).
_LAYOUT_PRESETS = {"light", "boxed", "bold", "striped"}
_FONT_STACKS = {
    "sans": "'DejaVu Sans', 'Helvetica', 'Arial', sans-serif",
    "serif": "'DejaVu Serif', 'Georgia', 'Times New Roman', serif",
}
_DEFAULT_SECONDARY = "#f6f8fb"  # the historical panel/zebra tint — zero-diff default


def document_brand_context(seller_company, *, is_demo: bool = False) -> dict:
    """The branding bundle every concrete document template feeds the base with. Resolves the
    seller's CompanyDocumentProfile + logo. Safe when `seller_company` is None (renders the
    neutral platform fallback — never fake counterparty data)."""
    from accounts.models import CompanyDocumentProfile

    # ONE read of the profile row (never creates).
    row = CompanyDocumentProfile.objects.filter(company=seller_company).first() if seller_company else None
    return _brand_context_from_row(seller_company, row, is_demo=is_demo)


def _brand_context_from_row(seller_company, row, *, is_demo: bool = False) -> dict:
    """Build the brand context from an ALREADY-FETCHED profile row (may be mutated in-memory by
    the caller — the draft-preview path applies unsaved overrides before delegating here).

    Branding (legal name / logo / requisites) only renders when actually filled
    (_profile_has_branding) → the template falls back to the Company otherwise. The layout
    TOGGLES and the document THEME (layout preset / font / secondary tint) read from the raw
    row regardless, so a seller can restyle documents without also filling their legal name.
    """
    from .quotes import _profile_has_branding

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
    # Theme reads from the RAW row (like the toggles) and is allowlist-validated at render
    # time too — defence-in-depth: layout lands in a class attr, secondary in a <style> block.
    raw_layout = getattr(row, "layout_preset", None) if row else None
    layout_preset = raw_layout if raw_layout in _LAYOUT_PRESETS else "light"
    raw_font = getattr(row, "font_family", None) if row else None
    font_stack = _FONT_STACKS.get(raw_font, _FONT_STACKS["sans"])
    raw_secondary = getattr(row, "secondary_color", None) if row else None
    secondary = raw_secondary if is_hex_color(raw_secondary) else _DEFAULT_SECONDARY
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
        # D2 document theme — one theme drives all the company's PDFs.
        "layout_preset": layout_preset,
        "font_stack": font_stack,
        "secondary": secondary,
    }


# ── КП «фирменный бланк»: сопроводительный текст + структурные условия (spec-kp-blank) ──


def _tidy_empty_substitutions(text: str) -> str:
    """Clean the punctuation residue an EMPTY token leaves behind.

    A flat substitution of «…за интерес, {{buyer}}.» with no buyer yields «…за интерес, .».
    Collapse the artifacts (empty brackets/quotes, space-before-punctuation, doubled
    punctuation, runs of spaces) so a missing counterparty never prints a dangling comma.
    Only runs when a token actually resolved to «» — normal seller text is left untouched.
    """
    text = re.sub(r"«\s*»|\(\s*\)|\"\s*\"", "", text)  # empty brackets/quotes
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)  # space before punctuation
    text = re.sub(r"([,;:])\s*([.,;:])", r"\2", text)  # doubled punctuation → keep the last
    text = re.sub(r"[ \t]{2,}", " ", text)  # collapse space runs
    text = re.sub(r"[ \t]+\n", "\n", text)  # trailing spaces per line
    return text.strip()


def resolve_cover_letter(profile, *, buyer_name: str = "", deal_ref: str = "", seller_name: str = "") -> str:
    """Resolved cover-letter paragraph, or "" when disabled/empty.

    FLAT token substitution ({{buyer}}/{{deal}}/{{seller}}) — the stored text is NEVER rendered
    as a Django template (no SSTI). Values are inserted raw; the caller's template prints it via
    `|linebreaks`, which auto-escapes, so an injected value can't become markup (no XSS).

    `deal_ref` fills {{deal}} — the buyer's REQUEST reference. A заявка has no formal number
    (owner decision 27-07), so callers pass its date («на Ваш запрос от 24.07.2026»).
    """
    if not profile or not getattr(profile, "show_cover_letter", False):
        return ""
    text = (getattr(profile, "cover_letter_text", "") or "").strip()
    if not text:
        return ""
    values = {
        "{{buyer}}": buyer_name or "",
        "{{deal}}": str(deal_ref or ""),
        "{{seller}}": seller_name or "",
    }
    had_empty = any(token in text and not value for token, value in values.items())
    for token, value in values.items():
        text = text.replace(token, value)
    return _tidy_empty_substitutions(text) if had_empty else text


def build_quote_terms(
    *,
    shipment_place: str = "",
    lead_days=None,
    delivery_note: str = "",
    payment: str = "",
    incoterm: str = "",
    warranty_months=None,
    valid_until: str = "",
    other: str = "",
) -> list:
    """The structured «Условия поставки» rows (label:value) for the КП blank.

    Everything except «Прочие условия» is DYNAMIC — sourced from КП / seller data, not retyped.
    Empty values are skipped so a blank line never prints. ONE builder (Rule 8) shared by the
    real render and the settings preview, so the two can't drift.
    """
    rows = []

    def add(label, value):
        if value not in (None, "", 0):
            rows.append({"label": label, "value": value})

    add("Место отгрузки", shipment_place)
    if lead_days:
        srok = f"до {lead_days} дн."
        if delivery_note:
            srok = f"{srok} · {delivery_note}"
        add("Сроки поставки", srok)
    elif delivery_note:
        add("Сроки поставки", delivery_note)
    add("Условия оплаты", payment)
    add("Базис поставки", incoterm)
    if warranty_months:
        add("Гарантия", f"{warranty_months} мес.")
    add("Срок действия КП", valid_until)
    add("Прочие условия", other)
    return rows


def quote_document_extras(quote, seller_company) -> dict:
    """The «фирменный бланк» extras shared by the КП PDF *and* its online twin (D1c): the resolved
    cover letter, the structured «Условия поставки», and the unified 3-line VAT totals. ONE builder
    so the PDF and the public page — the «оригинал» a client reaches by scanning the QR — can never
    diverge. Read-only (never creates a profile/settings row)."""
    from accounts.models import CompanyDocumentProfile, CompanySettings

    doc_profile = CompanyDocumentProfile.objects.filter(company=seller_company).first() if seller_company else None
    seller_settings = CompanySettings.objects.filter(company=seller_company).first() if seller_company else None
    buyer = quote.deal.company
    deal_created = getattr(quote.deal, "created_at", None)
    cover_text = resolve_cover_letter(
        doc_profile,
        buyer_name=getattr(buyer, "name", "") or "",
        deal_ref=deal_created.strftime("%d.%m.%Y") if deal_created else "",
        seller_name=getattr(seller_company, "name", "") or "",
    )
    incoterm = ""
    if quote.delivery_basis:
        incoterm = quote.delivery_basis.code
        if quote.delivery_basis.name:
            incoterm = f"{incoterm} ({quote.delivery_basis.name})"
    quote_terms = build_quote_terms(
        shipment_place=(getattr(doc_profile, "legal_address", "") or getattr(seller_company, "legal_address", "") or ""),
        lead_days=quote.effective_delivery_lead_time_days,
        delivery_note=quote.delivery_note or "",
        payment=getattr(seller_settings, "default_payment_terms", "") or "",
        incoterm=incoterm,
        warranty_months=getattr(seller_settings, "default_warranty_months", None),
        valid_until=quote.valid_until.strftime("%d.%m.%Y") if quote.valid_until else "",
        other=quote.notes or "",
    )
    totals = document_totals(
        ccy=quote.quote_currency.code if quote.quote_currency else "UZS",
        vat_rate=quote.vat_rate,
        subtotal=quote.total_excl_vat,
        vat_amount=quote.vat_amount,
        total=quote.total_incl_vat,
    )
    return {"cover_text": cover_text, "quote_terms": quote_terms, "totals": totals}


def document_totals(
    *,
    ccy: str,
    vat_rate=None,
    subtotal=None,
    vat_amount=None,
    total=None,
    amount_paid=None,
    balance_due=None,
) -> dict:
    """The uniform «Сумма без НДС → НДС X% → Итого к оплате» bridge for EVERY transactional PDF
    (КП / договор / инвойс / акт). D1: the four documents used three different totals formats
    («3 разных формата итогов НДС»); this single builder + the shared _totals_block.html partial
    give them one identical block.

    Pass whichever figures the model actually stores — the rest are derived:
      • gross `total` + `vat_rate` only (contract) → subtotal = total / (1 + rate/100);
      • `subtotal` + `vat_amount` (invoice/act) → total and the effective rate are derived.
    """
    from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

    def _dec(value):
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    subtotal_d, vat_d, total_d, rate = _dec(subtotal), _dec(vat_amount), _dec(total), _dec(vat_rate)
    if subtotal_d is None and total_d is not None:
        if rate and rate > 0:
            subtotal_d = (total_d / (Decimal(1) + rate / Decimal(100))).quantize(Decimal("0.01"), ROUND_HALF_UP)
        else:
            subtotal_d = total_d
    if vat_d is None and total_d is not None and subtotal_d is not None:
        vat_d = total_d - subtotal_d
    if total_d is None and subtotal_d is not None:
        total_d = subtotal_d + (vat_d or Decimal(0))
    if (rate is None or rate == 0) and subtotal_d and vat_d and subtotal_d > 0:
        rate = (vat_d / subtotal_d * Decimal(100)).quantize(Decimal("1"), ROUND_HALF_UP)
    return {
        "ccy": ccy or "UZS",
        "vat_rate": rate or Decimal(0),
        "subtotal": subtotal_d,
        "vat_amount": vat_d,
        "total": total_d,
        "amount_paid": _dec(amount_paid),
        "balance_due": _dec(balance_due),
    }
