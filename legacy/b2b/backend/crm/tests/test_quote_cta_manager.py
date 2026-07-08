"""Phase 2 КП conversion — the manager-contact block (prepared_by) and the «Принять онлайн» CTA
built from public_access_token (F-08/F-09). The CTA renders ONLY when a public link is present
(i.e. after send, token minted) — never on the draft PDF or the settings preview. Confidentiality
is unaffected: prepared_by is seller-side contact and the link is the buyer's own no-login КП."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string

from accounts.models import Company
from crm.services.documents import public_quote_url, render_document_profile_preview_html


def _ctx(**over):
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
        "fx_snapshot": {},
        "frozen_at": None,
        "updated_at": date(2026, 7, 8),
        "prepared_by": None,
    }
    quote.update(over.pop("quote", {}))
    ctx = {
        "quote": quote,
        "items": [],
        "company": Company(name="Buyer", inn="7700000000"),
        "seller": Company(name="Seller", inn="3000000000", phone="+998 90 111-22-33"),
        "seller_profile": None,
        "seller_logo_url": None,
        "is_demo": False,
        "public_quote_url": None,
    }
    ctx.update(over)
    return ctx


def _manager(full_name="Иван Петров", email="ivan@seller.uz", phone="+998 90 000-11-22"):
    return SimpleNamespace(get_full_name=lambda: full_name, email=email, phone=phone)


# ── manager block ────────────────────────────────────────────────────
def test_manager_block_renders_when_prepared_by_set():
    html = render_to_string("crm/quote_pdf.html", _ctx(quote={"prepared_by": _manager()}))
    assert "Ваш менеджер:" in html
    assert "Иван Петров" in html
    assert "ivan@seller.uz" in html
    assert "+998 90 000-11-22" in html


def test_manager_block_absent_when_no_prepared_by():
    html = render_to_string("crm/quote_pdf.html", _ctx())
    assert "Ваш менеджер" not in html


def test_manager_falls_back_to_email_and_seller_phone():
    mgr = SimpleNamespace(get_full_name=lambda: "", email="sales@seller.uz", phone="")
    html = render_to_string("crm/quote_pdf.html", _ctx(quote={"prepared_by": mgr}))
    assert "sales@seller.uz" in html
    assert "+998 90 111-22-33" in html  # seller.phone fallback


# ── online-accept CTA ────────────────────────────────────────────────
def test_cta_renders_when_public_url_present():
    url = "https://b2b.railtech.uz/api/v1/public/quotes/tok123/"
    html = render_to_string("crm/quote_pdf.html", _ctx(public_quote_url=url))
    assert "Принять предложение онлайн" in html
    assert url in html


def test_cta_absent_without_public_url():
    html = render_to_string("crm/quote_pdf.html", _ctx())
    assert "Принять предложение онлайн" not in html


def test_template_comment_does_not_leak_into_output():
    """A multi-line {# #} comment silently renders as visible text (must use {% comment %}).
    Guard the developer note near the manager/CTA block from ever printing on the КП."""
    html = render_to_string("crm/quote_pdf.html", _ctx(quote={"prepared_by": _manager()}))
    assert "no confidentiality impact" not in html
    assert "token minted" not in html


@pytest.mark.django_db
def test_preview_has_no_cta_or_leaked_token():
    """The settings preview renders a sample КП with no real token → no CTA (F-09 stays post-send)."""
    seller = Company.objects.create(name="Seller LLC", inn="3000000003")
    html = render_document_profile_preview_html(seller)
    assert "Принять предложение онлайн" not in html


# ── public_quote_url helper ──────────────────────────────────────────
def test_public_quote_url_none_without_token():
    assert public_quote_url(SimpleNamespace(public_access_token="")) is None
    assert public_quote_url(SimpleNamespace(public_access_token=None)) is None


def test_public_quote_url_built_from_token(settings):
    settings.FRONTEND_URL = "https://b2b.railtech.uz"
    url = public_quote_url(SimpleNamespace(public_access_token="abc123"))
    assert url == "https://b2b.railtech.uz/api/v1/public/quotes/abc123/"
