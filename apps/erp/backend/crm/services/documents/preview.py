"""Sample documents for the Document-Layout preview (Odoo wizard model).

The seller sees the theme on every report BEFORE saving. These render the SAME templates the
real PDFs render — the preview cannot drift from the product. They use representative sample
data (never a real document) and return HTML, not a PDF: instant, cheap to re-render on every
keystroke, and never WeasyPrint in the request thread (ARCH-03).

Rule 1 concerns PRODUCTION data paths; a clearly-labelled «образец» preview is the documented
exception.
"""

from decimal import Decimal

from .blank import build_quote_terms, resolve_cover_letter
from .brand import _brand_context_from_row
from .totals import document_totals

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

# Shared sample counterparty for every preview document.
_SAMPLE_BUYER = {
    "name": "ООО «Образец-Клиент»",
    "inn": "300000000",
    "legal_address": "г. Ташкент, ул. Примерная, 1",
    # КП-письмо: реквизит «адресат» (ГОСТ 7.0.97) — образец показывает строку «кому».
    "contact_person": "Директору Иванову К. К.",
}


def _apply_preview_overrides(row, overrides: dict) -> None:
    """Overlay UNSAVED theme-editor values onto an in-memory profile row (never .save())."""
    for field in _PREVIEW_TEXT_OVERRIDES:
        if field in overrides:
            setattr(row, field, overrides[field] or "")
    for field in _PREVIEW_BOOL_OVERRIDES:
        if field in overrides:
            value = overrides[field]
            if isinstance(value, str):
                value = value.strip().lower() in {"1", "true", "yes", "on"}
            setattr(row, field, bool(value))


def render_document_profile_preview_html(company, doc_type: str = "KP", overrides: dict = None) -> str:
    """Render a SAMPLE document of the requested kind (КП / договор / инвойс / акт / письмо) as
    HTML using the company's document profile, optionally overlaid with UNSAVED draft settings."""
    from accounts.models import CompanyDocumentProfile

    row = CompanyDocumentProfile.objects.filter(company=company).first()
    if overrides:
        if row is None:
            row = CompanyDocumentProfile(company=company)  # in-memory only — never .save()
        _apply_preview_overrides(row, overrides)
    brand = _brand_context_from_row(company, row)

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


def _sample_invoice_lines():
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


def _sample_quote_number(seller) -> str:
    """Владелец 27-07: «нумерация документа разрознена с настройками компании» — номер образца
    рендерится ПО СХЕМЕ НУМЕРАЦИИ продавца (dry-run, счётчик не трогается), а не хардкодом.
    A broken draft scheme must never kill the preview — it falls back to the stock sample."""
    fallback = "КП-2026-000123"
    if seller is None:
        return fallback
    from django.core.exceptions import ValidationError as DjangoValidationError

    from ..numbering import get_company_scheme_view, preview_scheme_numbers

    try:
        scheme_view = get_company_scheme_view(seller)
        rendered = preview_scheme_numbers(
            seller,
            pattern=scheme_view.scheme.pattern,
            padding=scheme_view.scheme.padding,
            reset_period=scheme_view.scheme.reset_period,
            start_value=scheme_view.scheme.start_value,
        )
        return next((row["number"] for row in rendered if row["type_code"] == "KP"), fallback)
    except (DjangoValidationError, ValueError):
        return fallback


def _sample_quote(brand: dict) -> dict:
    from datetime import date

    return {
        "quote_currency": {"code": "UZS"},
        "number": f"{_sample_quote_number(brand.get('seller'))} (образец)",
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
        # Т4 meta block WYSIWYG: a sample manager so the seller sees the header contacts styled.
        # Dict lookups satisfy the template's prepared_by.get_full_name/.phone/.email reads.
        "prepared_by": {
            "get_full_name": "Алексей Менеджеров",
            "phone": "+998 90 123-45-67",
            "email": "sales@company.uz",
        },
    }


def _sample_quote_items() -> list:
    return [
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


def _render_sample_quote_html(brand: dict, cover_profile=None) -> str:
    from django.template.loader import render_to_string

    sample_quote = _sample_quote(brand)
    # «Фирменный бланк» blocks in the preview (spec-kp-blank): cover letter resolved from the
    # (draft) profile so the seller sees it live; structured terms use representative sample values
    # (the preview is an «образец») + the shipment place from the branded requisites.
    # `seller_name` is composed in the template (firstof legal_name/name), not carried in the brand
    # dict — derive it here so the {{seller}} token resolves in the preview like it does live.
    seller_name = (
        getattr(brand.get("seller_profile"), "legal_name", "") or getattr(brand.get("seller"), "name", "") or ""
    )
    context = {
        "quote": sample_quote,
        "items": _sample_quote_items(),
        "optional_items": [],
        "company": _SAMPLE_BUYER,
        "cover_text": resolve_cover_letter(
            cover_profile, buyer_name=_SAMPLE_BUYER["name"], deal_ref="08.07.2026", seller_name=seller_name
        ),
        "quote_terms": build_quote_terms(
            shipment_place=(
                getattr(brand.get("seller_profile"), "legal_address", "") or "Республика Узбекистан, г. Ташкент"
            ),
            lead_days=21,
            payment="100% предоплата",
            incoterm="DAP (Ташкент)",
            warranty_months=12,
            valid_until="08.08.2026",
            other="При отсутствии модели у производителя может быть предложен аналог "
            "с соответствующими характеристиками.",
        ),
        # Shared 3-line VAT block (D1) — the preview mirrors the real render.
        "totals": document_totals(
            ccy="UZS",
            vat_rate=sample_quote["vat_rate"],
            subtotal=sample_quote["total_excl_vat"],
            vat_amount=sample_quote["vat_amount"],
            total=sample_quote["total_incl_vat"],
        ),
        # Branding preview, not a real export — no «ЧЕРНОВИК» stamp (it would obscure the very
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
