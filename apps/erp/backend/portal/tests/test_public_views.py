"""Tests for public unauthenticated views in portal app (M2-ERP-03).

Covers:
  - Public quote HTML viewing & content negotiation
  - 202 + Retry-After pattern for asynchronous PDF rendering
  - Quote acceptance via email code, rejection with reason
  - Public viewed beacon
  - Public document viewing & 202 polling
  - Reachability gating (NOT_FOUND -> 404, EXPIRED/REVOKED -> 410)
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone
from documents.models import GeneratedDocument
from parties.models import Company, Contact
from rest_framework.test import APIClient
from sales.models import Deal, Quote, QuoteStatus

from crm.constants import QuoteStatusCode


@pytest.fixture
def public_company(db):
    return Company.objects.create(name="Public Test Client Company", inn="1122334455")


@pytest.fixture
def public_contact(db, public_company):
    return Contact.objects.create(
        company=public_company,
        name="Test Recipient",
        email="client.recipient@example.uz",
        can_act=True,
    )


@pytest.fixture
def public_deal(db, public_company):
    from sales.models import DealStage

    from crm.constants import DealStageCode

    stage, _ = DealStage.objects.get_or_create(code=DealStageCode.QUOTE_SENT, defaults={"name": "КП отправлено"})
    return Deal.objects.create(company=public_company, title="Public Test Deal", stage=stage)


@pytest.fixture
def public_sent_quote(db, public_deal, public_contact):
    sent_status, _ = QuoteStatus.objects.get_or_create(code=QuoteStatusCode.SENT, defaults={"name": "Отправлено"})
    quote = Quote.objects.create(
        deal=public_deal,
        version=1,
        status=sent_status,
        frozen_at=timezone.now(),
        public_access_token="tok_PUBQUOTE_1234567890",
        valid_until=timezone.now().date() + timedelta(days=7),
    )
    quote.pdf_file.save("test_kp.pdf", ContentFile(b"%PDF-1.4 test stream content"), save=True)
    return quote


@pytest.fixture
def public_document(db, public_company, public_deal):
    from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocumentStatus

    kind, _ = DocumentTemplateKind.objects.get_or_create(code="LETTER", defaults={"name": "Письмо"})
    template, _ = DocumentTemplate.objects.get_or_create(
        company=public_company,
        name="Test Official Template",
        defaults={"kind": kind},
    )
    status_issued, _ = GeneratedDocumentStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Выпущен"})
    doc = GeneratedDocument.objects.create(
        company=public_company,
        deal=public_deal,
        template=template,
        status=status_issued,
        number="DOC-2026-00001",
        title="Official Letter",
        rendered_html="<html><body><h1>Test Document</h1></body></html>",
        public_access_token="tok_PUBDOC_1234567890",
    )
    doc.pdf_file.save("test_doc.pdf", ContentFile(b"%PDF-1.4 test doc stream"), save=True)
    return doc


# ── 1. Public Quote View & 202 Retry-After ────────────────────────────────────


@pytest.mark.django_db
def test_public_quote_html_page_served_for_browser(public_sent_quote):
    client = APIClient()
    url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/"
    resp = client.get(url, HTTP_ACCEPT="text/html,application/xhtml+xml", SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert "text/html" in resp["Content-Type"]


@pytest.mark.django_db
def test_public_quote_pdf_streaming_when_file_present(public_sent_quote):
    client = APIClient()
    url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/"
    with mock.patch("crm.tasks.render_document_pdf.delay") as render_delay:
        resp = client.get(url, HTTP_ACCEPT="application/pdf", SERVER_NAME="localhost")
    assert resp.status_code == 200
    render_delay.assert_not_called()


@pytest.mark.django_db
def test_public_quote_returns_202_retry_after_when_pdf_missing(public_sent_quote):
    public_sent_quote.pdf_file.delete(save=True)
    client = APIClient()
    url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/?export=pdf"

    with mock.patch("crm.tasks.render_document_pdf.delay") as render_delay:
        resp = client.get(url, HTTP_ACCEPT="application/json", SERVER_NAME="localhost")

    assert resp.status_code == 202
    assert resp["Retry-After"] == "2"
    assert resp.data["detail"] == "GENERATING"
    render_delay.assert_called_once_with("quote", public_sent_quote.pk)


@pytest.mark.django_db
def test_public_quote_browser_html_returns_202_generating_template_when_pdf_missing(public_sent_quote):
    public_sent_quote.pdf_file.delete(save=True)
    client = APIClient()
    url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/?export=pdf"

    with mock.patch("crm.tasks.render_document_pdf.delay"):
        resp = client.get(url, HTTP_ACCEPT="text/html", SERVER_NAME="localhost")

    assert resp.status_code == 202
    assert resp["Retry-After"] == "2"
    assert "text/html" in resp["Content-Type"]


@pytest.mark.django_db
def test_public_quote_not_found():
    client = APIClient()
    resp = client.get("/api/v1/public/quotes/nonexistent_token/", HTTP_ACCEPT="application/json")
    assert resp.status_code == 404
    assert resp.data["detail"] == "NOT_FOUND"


@pytest.mark.django_db
def test_public_quote_expired_returns_410(public_sent_quote):
    public_sent_quote.valid_until = timezone.now().date() - timedelta(days=1)
    public_sent_quote.save(update_fields=["valid_until"])

    client = APIClient()
    url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/"
    resp = client.get(url, HTTP_ACCEPT="application/json")
    assert resp.status_code == 410
    assert resp.data["detail"] == "QUOTE_LINK_EXPIRED"


# ── 2. Public Quote Actions (Beacon, Code, Accept, Reject) ────────────────────


@pytest.mark.django_db
def test_public_quote_viewed_beacon(public_sent_quote):
    client = APIClient()
    url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/viewed/"
    resp = client.post(url)
    assert resp.status_code == 204
    public_sent_quote.refresh_from_db()
    assert public_sent_quote.first_viewed_at is not None


@pytest.mark.django_db
def test_public_quote_request_code_and_accept_flow(public_sent_quote):
    client = APIClient()
    req_code_url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/request-code/"
    resp_code = client.post(req_code_url)
    assert resp_code.status_code == 200

    accept_url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/accept/"
    # Invalid code -> 400
    resp_invalid = client.post(accept_url, {"code": "000000"}, format="json")
    assert resp_invalid.status_code == 400

    # With verified code mock
    with mock.patch("crm.services.public_page.verify_code_and_accept") as mock_verify:
        mock_verify.return_value = (public_sent_quote, None)
        resp_valid = client.post(accept_url, {"code": "123456"}, format="json")
    assert resp_valid.status_code == 200
    assert resp_valid.data["detail"] == "ACCEPTED"


@pytest.mark.django_db
def test_public_quote_reject_flow(public_sent_quote):
    client = APIClient()
    reject_url = f"/api/v1/public/quotes/{public_sent_quote.public_access_token}/reject/"

    # Empty reason -> 400 REASON_REQUIRED
    resp_empty = client.post(reject_url, {"reason": ""}, format="json")
    assert resp_empty.status_code == 400

    # Valid reason -> 200 REJECTED
    resp_ok = client.post(reject_url, {"reason": "Цена не устраивает"}, format="json")
    assert resp_ok.status_code == 200
    assert resp_ok.data["detail"] == "REJECTED"


# ── 3. Public Document View & Script ──────────────────────────────────────────


@pytest.mark.django_db
def test_public_document_html_view(public_document):
    client = APIClient()
    url = f"/api/v1/public/documents/{public_document.public_access_token}/"
    resp = client.get(url, HTTP_ACCEPT="text/html", SERVER_NAME="localhost")
    assert resp.status_code == 200
    assert "text/html" in resp["Content-Type"]


@pytest.mark.django_db
def test_public_document_pdf_stream(public_document):
    client = APIClient()
    url = f"/api/v1/public/documents/{public_document.public_access_token}/"
    resp = client.get(url, HTTP_ACCEPT="application/pdf", SERVER_NAME="localhost")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_public_document_returns_202_when_pdf_missing(public_document):
    public_document.pdf_file.delete(save=True)
    client = APIClient()
    url = f"/api/v1/public/documents/{public_document.public_access_token}/?export=pdf"

    with mock.patch("crm.tasks.render_document_pdf.delay") as render_delay:
        resp = client.get(url, HTTP_ACCEPT="application/json", SERVER_NAME="localhost")

    assert resp.status_code == 202
    assert resp["Retry-After"] == "2"
    assert resp.data["detail"] == "GENERATING"
    render_delay.assert_called_once_with("generated", public_document.id)


@pytest.mark.django_db
def test_public_quote_page_script_view():
    client = APIClient()
    resp = client.get("/api/v1/public/quote-page.js")
    assert resp.status_code == 200
    assert "javascript" in resp["Content-Type"]
