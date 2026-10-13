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
from crm.services.documents import public_quote_qr, public_quote_url, render_document_profile_preview_html


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


# ── manager contacts (Т4: живут в мета-блоке шапки, не в хвосте документа) ───────
def test_manager_renders_in_header_meta_when_prepared_by_set():
    html = render_to_string("crm/quote_pdf.html", _ctx(quote={"prepared_by": _manager()}))
    meta = html.split('class="meta-grid"')[1].split("</table>")[0]
    assert "Менеджер" in meta
    assert "Иван Петров" in meta
    assert "ivan@seller.uz" in meta
    assert "+998 90 000-11-22" in meta


def test_manager_meta_absent_when_no_prepared_by():
    html = render_to_string("crm/quote_pdf.html", _ctx())
    meta = html.split('class="meta-grid"')[1].split("</table>")[0]
    assert "Менеджер" not in meta
    assert "Дата" in meta  # the date rows still print


def test_manager_falls_back_to_email_and_seller_phone():
    mgr = SimpleNamespace(get_full_name=lambda: "", email="sales@seller.uz", phone="")
    html = render_to_string("crm/quote_pdf.html", _ctx(quote={"prepared_by": mgr}))
    meta = html.split('class="meta-grid"')[1].split("</table>")[0]
    assert "sales@seller.uz" in meta
    assert "+998 90 111-22-33" in meta  # seller.phone fallback


# ── online-accept CTA ────────────────────────────────────────────────
def test_cta_renders_when_public_url_present():
    url = "https://b2b.railtech.uz/api/v1/public/quotes/tok123/"
    html = render_to_string("crm/quote_pdf.html", _ctx(public_quote_url=url))
    assert "Онлайн-версия предложения" in html
    assert url in html


def test_cta_absent_without_public_url():
    html = render_to_string("crm/quote_pdf.html", _ctx())
    assert "Онлайн-версия предложения" not in html


# ── online-accept QR (F-09) ──────────────────────────────────────────
def test_cta_qr_img_renders_when_qr_present():
    url = "https://b2b.railtech.uz/api/v1/public/quotes/tok123/"
    qr = "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="
    html = render_to_string("crm/quote_pdf.html", _ctx(public_quote_url=url, public_quote_qr=qr))
    assert 'class="cta-qr"' in html
    assert qr in html
    assert "Отсканируйте QR" in html


def test_cta_qr_img_absent_when_no_qr_but_link_stays():
    url = "https://b2b.railtech.uz/api/v1/public/quotes/tok123/"
    html = render_to_string("crm/quote_pdf.html", _ctx(public_quote_url=url))
    assert 'class="cta-qr"' not in html
    assert url in html  # the text-link CTA still renders without the QR


# ── public_quote_qr helper ───────────────────────────────────────────
def test_public_quote_qr_none_without_token():
    assert public_quote_qr(SimpleNamespace(public_access_token="")) is None
    assert public_quote_qr(SimpleNamespace(public_access_token=None)) is None


def test_public_quote_qr_returns_svg_data_uri(settings):
    settings.FRONTEND_URL = "https://b2b.railtech.uz"
    uri = public_quote_qr(SimpleNamespace(public_access_token="abc123"))
    assert uri is not None
    assert uri.startswith("data:image/svg+xml;base64,")
    # decodes to real SVG markup (not empty / not a stray error)
    import base64

    decoded = base64.b64decode(uri.split(",", 1)[1]).decode("utf-8")
    assert "<svg" in decoded and "path" in decoded


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
    assert "Онлайн-версия предложения" not in html


# ── public_quote_url helper ──────────────────────────────────────────
def test_public_quote_url_none_without_token():
    assert public_quote_url(SimpleNamespace(public_access_token="")) is None
    assert public_quote_url(SimpleNamespace(public_access_token=None)) is None


def test_public_quote_url_built_from_token(settings):
    settings.FRONTEND_URL = "https://b2b.railtech.uz"
    url = public_quote_url(SimpleNamespace(public_access_token="abc123"))
    assert url == "https://b2b.railtech.uz/api/v1/public/quotes/abc123/"
