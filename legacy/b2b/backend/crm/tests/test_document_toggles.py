"""P3 document-settings toggles — the seller controls what its documents show:
  show_lead_time  → the «Срок» column on the КП
  show_fx_note    → the CBU FX-basis note on the client КП (off by default)
  show_logo       → the logo in the document header
Plus the live-preview service that renders a SAMPLE КП from the company's current profile.
Templates rendered via render_to_string (no WeasyPrint), same approach as the sibling tests.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.template.loader import render_to_string

from accounts.models import Company, CompanyDocumentProfile
from crm.services.documents import document_brand_context, render_document_profile_preview_html


def _quote_ctx(**toggles):
    items = [
        {
            "product": None,
            "imported_raw_name": "Подшипник",
            "mpn": "",
            "gost_drawing": "",
            "quantity": 2,
            "unit": "шт.",
            "lead_time_days": 14,
            "final_price_excl_vat": Decimal("100.00"),
            "line_total": Decimal("200.00"),
        }
    ]
    quote = {
        "quote_currency": {"code": "UZS"},
        "number": "КП-1",
        "deal_id": 1,
        "version": 1,
        "created_at": date(2026, 7, 8),
        "valid_until": None,
        "subtotal_excl_vat": Decimal("200.00"),
        "charges_total": Decimal("0"),
        "total_excl_vat": Decimal("200.00"),
        "vat_rate": Decimal("12"),
        "vat_amount": Decimal("24.00"),
        "total_incl_vat": Decimal("224.00"),
        "effective_delivery_lead_time_days": 14,
        "delivery_basis": None,
        "delivery_note": "",
        "notes": "",
        "fx_snapshot": {"USD": "12500.00"},
        "frozen_at": None,
        "updated_at": date(2026, 7, 8),
    }
    buyer = Company(name="Buyer", inn="7700000000")
    ctx = {
        "quote": quote,
        "items": items,
        "company": buyer,
        "seller": Company(name="Seller", inn="3000000000"),
        "seller_profile": None,
        "seller_logo_url": None,
        "is_demo": False,
        "show_logo": True,
        "show_lead_time": True,
        "show_fx_note": False,
    }
    ctx.update(toggles)
    return ctx


def test_lead_time_column_shown_by_default():
    html = render_to_string("crm/quote_pdf.html", _quote_ctx(show_lead_time=True))
    assert "Срок" in html


def test_lead_time_column_hidden_when_toggle_off():
    html = render_to_string("crm/quote_pdf.html", _quote_ctx(show_lead_time=False))
    # The «Срок» column header is gone; the offer still renders.
    assert '<th style="width:12%" class="center">Срок</th>' not in html
    assert "Коммерческое предложение" in html


def test_fx_note_never_shown_on_client_quote():
    """CONFIDENTIALITY: the CBU/FX rate must NEVER appear on the client КП — printing it lets the
    buyer divide the UZS price by the rate to recover the seller's foreign-currency cost basis
    (sourcing leak). The show_fx_note seller toggle no longer renders it, even when ON."""
    for toggle in (False, True):
        html = render_to_string("crm/quote_pdf.html", _quote_ctx(show_fx_note=toggle))
        assert "Курс ЦБ" not in html
        assert "12500" not in html
        assert "пересчитаны" not in html


def test_logo_hidden_when_toggle_off():
    with_logo = _quote_ctx(seller_logo_url="http://x/logo.png", show_logo=True)
    without = _quote_ctx(seller_logo_url="http://x/logo.png", show_logo=False)
    assert "logo.png" in render_to_string("crm/quote_pdf.html", with_logo)
    assert "logo.png" not in render_to_string("crm/quote_pdf.html", without)


# ── brand-context toggle resolution ──────────────────────────────────
@pytest.mark.django_db
def test_brand_context_resolves_toggles_from_profile():
    seller = Company.objects.create(name="Seller LLC", inn="3000000001")
    CompanyDocumentProfile.objects.create(company=seller, show_logo=False, show_lead_time=False, show_fx_note=True)
    ctx = document_brand_context(seller)
    assert ctx["show_logo"] is False
    assert ctx["show_lead_time"] is False
    assert ctx["show_fx_note"] is True


def test_brand_context_safe_defaults_without_profile():
    ctx = document_brand_context(None)
    assert ctx["show_logo"] is True
    assert ctx["show_lead_time"] is True
    assert ctx["show_fx_note"] is False


# ── live preview ─────────────────────────────────────────────────────
@pytest.mark.django_db
def test_preview_html_reflects_profile_branding_and_toggles():
    seller = Company.objects.create(name="Seller LLC", inn="3000000002")
    CompanyDocumentProfile.objects.create(
        company=seller, legal_name="ООО «Превью Тест»", show_lead_time=False, show_fx_note=True
    )
    html = render_document_profile_preview_html(seller)
    assert "ООО «Превью Тест»" in html  # branding applied
    assert "Подшипник буксовый ЦКБ тип 2726" in html  # sample data
    # lead-time COLUMN suppressed by the toggle (the «Срок поставки» delivery term still shows).
    assert '<th style="width:12%" class="center">Срок</th>' not in html
    # CONFIDENTIALITY: even with show_fx_note=True on the profile, the client КП never prints the
    # CBU/FX rate — the toggle no longer leaks the seller's foreign-currency cost basis.
    assert "Курс ЦБ" not in html


@pytest.mark.django_db
def test_brand_context_neutralizes_non_hex_accent():
    """SEC audit #9 (defence-in-depth): a historical non-hex accent_color is neutralized to the
    default at render time, so it never reaches the <style> block even if it bypassed input
    validation."""
    seller = Company.objects.create(name="Seller LLC", inn="3000000099")
    CompanyDocumentProfile.objects.create(company=seller, legal_name="ООО Тест", accent_color="red;url(//1.1.1.1)")
    ctx = document_brand_context(seller)
    assert ctx["accent"] == "#15294d"
