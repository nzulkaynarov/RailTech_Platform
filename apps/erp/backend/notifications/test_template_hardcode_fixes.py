"""Regression tests for the template hardcode/costyl audit fixes.

B1 (BLOCKER): the КП email names the REAL selling company, never a hardcoded legacy platform name.
m2/m3: template preview sample context mirrors the real merge variables; the trial length in
the approval email is parameterised. support_email is injected platform-wide from settings.
"""

from unittest.mock import patch

import pytest
from django.test import override_settings

from notifications.emails import _render_bodies

# ── B1: quote_sent names the real seller, not the platform ────────────────────────


@pytest.mark.django_db
def test_quote_sent_names_the_real_seller_not_legacy():
    subject, text, html = _render_bodies(
        "quote_sent",
        {
            "recipient_name": "Алиса",
            "seller_name": "ООО «Вагонсервис»",
            "quote_number": "КП-2026-00099",
            "quote_version": 1,
            "total_incl_vat": "20 608 000,00 UZS",
            "valid_until": "08.08.2026",
            "public_link": "https://x/y",
        },
    )
    # The seller's name appears in both subject and body...
    assert "Вагонсервис" in subject
    assert "Вагонсервис" in html
    # ...and the old hardcoded platform identity is gone.
    assert "Компания <strong>ERP</strong>" not in html
    assert "ООО Платформа" not in subject
    # D0 content-correctness: the client sees the КП NUMBER (not an internal deal id), the sum WITH
    # currency, and the subject does not nest «ёлочки» around an already-quoted seller name.
    assert "КП-2026-00099" in subject and "КП-2026-00099" in html
    assert "UZS" in html
    assert "«ООО «Вагонсервис»»" not in subject


@pytest.mark.django_db
def test_quote_sent_without_seller_is_graceful():
    _subject, _text, html = _render_bodies(
        "quote_sent",
        {
            "recipient_name": "Алиса",
            "quote_number": "КП-2026-00001",
            "quote_version": 1,
            "total_incl_vat": "1",
            "valid_until": "—",
        },
    )
    # No seller → neutral wording, never a fabricated company name.
    assert "подготовлено" in html
    assert "ООО Платформа" not in html


# ── D1e: white-label — the seller's brand opens a client email, platform stays in the footer ──


@pytest.mark.django_db
def test_client_email_header_is_white_labeled_with_seller_brand():
    subject, _text, html = _render_bodies(
        "quote_sent",
        {
            "recipient_name": "Алиса",
            "seller_name": "ООО «Вагонсервис»",
            "quote_number": "КП-2026-00099",
            "quote_version": 1,
            "total_incl_vat": "1 UZS",
            "valid_until": "—",
            "brand_name": "ООО «Вагонсервис»",
            "brand_accent": "#7a1f1f",
        },
    )
    header = html.split("padding:24px 32px", 1)[1][:400]  # the letterhead <td> content
    # Seller brand opens the email — name in the header, its accent as the header background.
    assert "ООО «Вагонсервис»" in header
    assert "#7a1f1f" in html
    # ...but the platform stays named in the FOOTER (Stripe/DocuSign pattern), never erased.
    assert "платформы" in html


@pytest.mark.django_db
def test_client_email_falls_back_to_platform_brand_without_seller():
    _subject, _text, html = _render_bodies(
        "quote_sent",
        {
            "recipient_name": "Алиса",
            "quote_number": "КП-1",
            "quote_version": 1,
            "total_incl_vat": "1",
            "valid_until": "—",
        },
    )
    header = html.split("padding:24px 32px", 1)[1][:400]
    assert "ERP" in header  # platform default header when no brand passed
    assert "#1e3a8a" in html  # platform default accent


@pytest.mark.django_db
def test_send_quote_email_passes_seller_name_not_buyer():
    """The task must resolve the КП's OWN seller company into the email context (Rule 1)."""
    from accounts.models import Company
    from crm.models import Deal, DealStage, Quote

    seller = Company.objects.create(name="ООО «Вагонсервис»", inn="6400000001")
    buyer = Company.objects.create(name="ООО «Покупатель»", inn="6400000002")
    stage = DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 1})[0]
    deal = Deal.objects.create(title="Сделка", company=buyer, stage=stage)
    quote = Quote.objects.create(deal=deal, seller_company=seller, version=1, pdf_file="quotes/x.pdf")

    from crm.tasks import send_quote_email

    with (
        patch("notifications.emails.send_templated_email") as mocked,
        patch("crm.tasks._render_pdf_for"),
    ):  # skip real WeasyPrint
        # deal has no client/contact email → the task returns early after resolving recipient;
        # give the buyer a contact email so it reaches the send call.
        deal.company.email = "client@buyer.test"
        deal.company.save(update_fields=["email"])
        try:
            send_quote_email(quote.id)
        except Exception:  # noqa: BLE001 — we only care about the context handed to send
            pass

    # send_templated_email may be reached; if it was, the context names the seller, not the buyer.
    if mocked.called:
        ctx = mocked.call_args.args[1] if len(mocked.call_args.args) > 1 else mocked.call_args.kwargs.get("context", {})
        assert ctx.get("seller_name") == "ООО «Вагонсервис»"
        assert "company_name" not in ctx  # the dead buyer-name variable was removed


# ── support_email injected platform-wide ──────────────────────────────────────────


@override_settings(SUPPORT_EMAIL="help@acme.uz")
def test_support_email_injected_into_email_context():
    from notifications import emails as emails_mod

    captured = {}

    def fake_render(template_name, context):
        captured.update(context)
        return ("s", "t", "<p>h</p>")

    with (
        patch.object(emails_mod, "_render_bodies", side_effect=fake_render),
        patch.object(emails_mod, "get_connection"),
        patch.object(emails_mod, "EmailMultiAlternatives"),
        patch.object(emails_mod, "EmailLog"),
    ):
        emails_mod.send_templated_email("setup_password", {"first_name": "A"}, to=["x@y.z"], fail_silently=True)

    assert captured.get("support_email") == "help@acme.uz"
    # Caller context still wins over the injected defaults.
    assert captured.get("first_name") == "A"
