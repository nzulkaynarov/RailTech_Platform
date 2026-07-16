"""SEC-tail (audit #17): the public КП token link now honours a TTL + revoke.

The emailed no-login link used to live forever and ignore the КП's own validity.
PublicQuoteView now gates on crm.services.quotes.public_quote_gate:
  * revoked link           → 410 QUOTE_LINK_REVOKED
  * EXPIRED status         → 410 QUOTE_LINK_EXPIRED
  * valid_until in the past→ 410 QUOTE_LINK_EXPIRED
  * public_token_expires_at in the past → 410 QUOTE_LINK_EXPIRED
Back-compat: a live SENT link (revoked=False, expires_at=NULL, valid_until unset
or future) still streams the PDF (200).
"""

from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company
from crm.models import Deal, Quote, QuoteStatus


def _make_quote(**overrides):
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Отправлено", "sort_order": 50})
    QuoteStatus.objects.get_or_create(code="EXPIRED", defaults={"name": "Просрочено", "sort_order": 60})
    company = Company.objects.create(name="Client Co", is_registered=False)
    deal = Deal.objects.create(company=company)
    fields = dict(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        frozen_at=timezone.now(),
        public_access_token=overrides.pop("token", "tok_TTL_TESTTOKEN"),
    )
    fields.update(overrides)
    quote = Quote.objects.create(**fields)
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
    return quote


def _get(quote):
    return APIClient().get(f"/api/v1/public/quotes/{quote.public_access_token}/", SERVER_NAME="localhost")


@pytest.mark.django_db
def test_live_link_without_ttl_still_streams_200():
    """Existing link: not revoked, no explicit TTL, no valid_until → still works (back-compat)."""
    quote = _make_quote()
    assert quote.public_token_revoked is False
    assert quote.public_token_expires_at is None
    resp = _get(quote)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_future_valid_until_streams_200():
    quote = _make_quote(valid_until=(timezone.now() + timedelta(days=7)).date())
    assert _get(quote).status_code == 200


@pytest.mark.django_db
def test_revoked_link_returns_410():
    quote = _make_quote(public_token_revoked=True)
    resp = _get(quote)
    assert resp.status_code == 410
    assert resp.data == {"detail": "QUOTE_LINK_REVOKED"}


@pytest.mark.django_db
def test_expired_valid_until_returns_410():
    quote = _make_quote(valid_until=(timezone.now() - timedelta(days=1)).date())
    resp = _get(quote)
    assert resp.status_code == 410
    assert resp.data == {"detail": "QUOTE_LINK_EXPIRED"}


@pytest.mark.django_db
def test_expired_status_returns_410():
    quote = _make_quote(status=QuoteStatus.objects.get(code="EXPIRED"))
    resp = _get(quote)
    assert resp.status_code == 410
    assert resp.data == {"detail": "QUOTE_LINK_EXPIRED"}


@pytest.mark.django_db
def test_token_ttl_in_the_past_returns_410():
    quote = _make_quote(public_token_expires_at=timezone.now() - timedelta(hours=1))
    resp = _get(quote)
    assert resp.status_code == 410
    assert resp.data == {"detail": "QUOTE_LINK_EXPIRED"}


@pytest.mark.django_db
def test_unknown_token_still_404():
    resp = APIClient().get("/api/v1/public/quotes/nope-nonexistent/", SERVER_NAME="localhost")
    assert resp.status_code == 404
    assert resp.data == {"detail": "NOT_FOUND"}


@pytest.mark.django_db
def test_browser_gets_friendly_html_not_raw_json_on_expired():
    """A browser (Accept: text/html) opening an expired link must see a human page, not the raw
    DRF/JSON error — the emailed link opens THIS endpoint directly (no SPA in front)."""
    quote = _make_quote(valid_until=timezone.now() - timedelta(days=1))
    resp = APIClient().get(
        f"/api/v1/public/quotes/{quote.public_access_token}/",
        HTTP_ACCEPT="text/html",
        SERVER_NAME="localhost",
    )
    assert resp.status_code == 410
    assert resp["Content-Type"].startswith("text/html")
    body = resp.content.decode()
    assert "Срок ссылки истёк" in body
    assert "QUOTE_LINK_EXPIRED" not in body  # machine code stays out of the human page


@pytest.mark.django_db
def test_browser_gets_friendly_html_on_revoked_and_unknown():
    """Revoked (410) and unknown-token (404) also render the friendly HTML for browsers."""
    quote = _make_quote(public_token_revoked=True)
    revoked = APIClient().get(
        f"/api/v1/public/quotes/{quote.public_access_token}/",
        HTTP_ACCEPT="text/html",
        SERVER_NAME="localhost",
    )
    assert revoked.status_code == 410
    assert "Ссылка отозвана" in revoked.content.decode()

    unknown = APIClient().get(
        "/api/v1/public/quotes/nope-nonexistent/", HTTP_ACCEPT="text/html", SERVER_NAME="localhost"
    )
    assert unknown.status_code == 404
    assert unknown["Content-Type"].startswith("text/html")
    assert "Ссылка не найдена" in unknown.content.decode()
