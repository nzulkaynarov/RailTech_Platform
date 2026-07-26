"""spec-kp-blank pilot (K1+K2a): cover-letter paragraph, dynamic structured «Условия поставки»,
bank requisites in the letterhead. Plus the SSTI/XSS safety of the cover-letter resolver.
"""

import pytest

from crm.services.documents import build_quote_terms, resolve_cover_letter


class _Profile:
    def __init__(self, show=True, text=""):
        self.show_cover_letter = show
        self.cover_letter_text = text


# ── Cover-letter resolver: flat substitution, no SSTI/XSS ─────────────────────────


def test_cover_letter_substitutes_tokens():
    out = resolve_cover_letter(
        _Profile(text="{{seller}} благодарит {{buyer}} за заявку {{deal}}."),
        buyer_name="ООО «Клиент»",
        deal_number="КП-2026-42",
        seller_name="ООО «Продавец»",
    )
    assert out == "ООО «Продавец» благодарит ООО «Клиент» за заявку КП-2026-42."


def test_cover_letter_disabled_or_empty_returns_blank():
    assert resolve_cover_letter(_Profile(show=False, text="x"), buyer_name="B") == ""
    assert resolve_cover_letter(_Profile(show=True, text="   "), buyer_name="B") == ""
    assert resolve_cover_letter(None, buyer_name="B") == ""


def test_cover_letter_is_not_a_template_engine_no_ssti():
    # A Django-template payload in the stored text must NOT be evaluated — flat replace only.
    out = resolve_cover_letter(
        _Profile(text="{% raw %}{{7*7}}{% endraw %} {{buyer}}"),
        buyer_name="ООО «Х»",
    )
    assert "49" not in out
    assert "{{7*7}}" in out  # left literal
    assert "ООО «Х»" in out


# ── Structured terms builder: dynamic, empties skipped, «Прочие» last ─────────────


def test_build_quote_terms_skips_empties_and_orders():
    rows = build_quote_terms(
        shipment_place="г. Ташкент",
        lead_days=60,
        payment="100% предоплата",
        incoterm="DAP (Ташкент)",
        warranty_months=12,
        valid_until="30.06.2026",
        other="Возможен аналог.",
    )
    labels = [r["label"] for r in rows]
    assert labels == [
        "Место отгрузки",
        "Сроки поставки",
        "Условия оплаты",
        "Базис поставки",
        "Гарантия",
        "Срок действия КП",
        "Прочие условия",
    ]
    assert rows[1]["value"] == "до 60 дн."
    assert rows[4]["value"] == "12 мес."


def test_build_quote_terms_omits_blank_rows():
    rows = build_quote_terms(payment="", warranty_months=None, valid_until="30.06.2026")
    labels = [r["label"] for r in rows]
    assert labels == ["Срок действия КП"]  # everything else blank → skipped


def test_build_quote_terms_lead_with_delivery_note():
    rows = build_quote_terms(lead_days=30, delivery_note="самовывоз")
    assert rows[0] == {"label": "Сроки поставки", "value": "до 30 дн. · самовывоз"}


# ── End-to-end via the settings preview (same template the real PDF renders) ──────


@pytest.mark.django_db
def test_preview_kp_renders_cover_terms_and_bank():
    from accounts.models import Company

    company = Company.objects.create(name="ООО «Бланк-Тест»", inn="6500000001")
    from crm.services.documents import render_document_profile_preview_html

    html = render_document_profile_preview_html(
        company,
        doc_type="KP",
        overrides={
            "show_cover_letter": True,
            "cover_letter_text": "Уважаемый {{buyer}}, благодарим за интерес.",
            "show_bank_in_header": True,
            "bank_details": "АИКБ «IPAK YOLI», МФО 00421, р/с 20208",
            "legal_name": "ООО «Бланк-Тест»",
        },
    )
    assert "Уважаемый ООО «Образец-Клиент», благодарим за интерес." in html
    assert "Условия поставки" in html and "100% предоплата" in html
    assert "brand-bank" in html and "МФО 00421" in html
    # Guard: Django comment markers must NOT leak into the rendered document — a MULTI-LINE {# #}
    # is printed literally by Django (must use {% comment %}). Caught by eyes-on on prod. (CSS
    # /* */ comments are fine; we only forbid the Django-template delimiters.)
    assert "{#" not in html and "#}" not in html
    assert "{% comment" not in html
    assert "плоская подстановка" not in html  # a phrase that lived inside the leaked comment


@pytest.mark.django_db
def test_preview_kp_cover_xss_escaped():
    from accounts.models import Company

    company = Company.objects.create(name="ООО «XSS-Тест»", inn="6500000002")
    from crm.services.documents import render_document_profile_preview_html

    html = render_document_profile_preview_html(
        company,
        doc_type="KP",
        overrides={"show_cover_letter": True, "cover_letter_text": "<script>alert(1)</script>"},
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ── brand_context_for_pdf: logo inlined as data: URI for WeasyPrint ────────────────


def test_brand_context_for_pdf_inlines_relative_media_logo(tmp_path, settings):
    """Prod (FileSystemStorage) yields a RELATIVE /media/… logo URL that WeasyPrint cannot
    resolve (HTML(string=…) has no base_url and fetches nothing) — every prod PDF printed a
    broken-image box. The PDF render path must inline the file as a data: URI."""
    from django.core.files.storage import default_storage

    from crm.services.documents import brand_context_for_pdf

    settings.MEDIA_ROOT = str(tmp_path)
    name = default_storage.save("companies/logos/test-logo.png", __import__("io").BytesIO(b"\x89PNG fake"))
    brand = brand_context_for_pdf({"seller_logo_url": settings.MEDIA_URL + name, "accent": "#15294d"})
    assert brand["seller_logo_url"].startswith("data:image/png;base64,")
    assert brand["accent"] == "#15294d"  # rest of the context untouched


def test_brand_context_for_pdf_leaves_absolute_urls_and_none(settings):
    from crm.services.documents import brand_context_for_pdf

    absolute = {"seller_logo_url": "http://minio:9000/bucket/logo.png?sig=x"}
    assert brand_context_for_pdf(absolute)["seller_logo_url"] == absolute["seller_logo_url"]
    assert brand_context_for_pdf({"seller_logo_url": None})["seller_logo_url"] is None


def test_brand_context_for_pdf_missing_file_degrades_to_no_logo(tmp_path, settings):
    """A dangling storage key must degrade to «no logo» (text letterhead), never a broken box."""
    from crm.services.documents import brand_context_for_pdf

    settings.MEDIA_ROOT = str(tmp_path)
    brand = brand_context_for_pdf({"seller_logo_url": settings.MEDIA_URL + "companies/logos/gone.png"})
    assert brand["seller_logo_url"] is None
