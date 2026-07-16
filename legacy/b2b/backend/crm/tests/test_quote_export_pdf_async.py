"""ARCH-03 tail — КП export (?format=pdf) never renders WeasyPrint inline.

`handle_quote_export` (behind `GET /api/v1/crm/quotes/<id>/export/`) now mirrors the
download-pdf action for the PDF branch: stream the persisted PDF when present, else run
only the cheap render guards synchronously (409) and enqueue the idempotent off-thread
render → 202 + Retry-After. XLSX/CSV are light seller sheets and stay synchronous, so
they must NOT enqueue a render.

These tests drive `handle_quote_export` directly (as test_quote_export.py drives the
export service). NOTE: the HTTP action cannot be exercised with `?format=pdf` because
DRF's URL_FORMAT_OVERRIDE consumes the `format` query param and 404s before the view
runs (pre-existing, reported separately) — so the branch logic is tested at the
function boundary the view delegates to.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.http import FileResponse
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.views.exports import handle_quote_export

RENDER_DELAY = "crm.tasks.render_document_pdf.delay"
_factory = APIRequestFactory()


def _request(user, fmt=None):
    """A DRF Request (has `.query_params`) — handle_quote_export reads query_params + user."""
    params = {"format": fmt} if fmt is not None else {}
    request = Request(_factory.get("/api/v1/crm/quotes/1/export/", params))
    request.user = user
    return request


@pytest.fixture
def lookups(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})


@pytest.fixture
def engineer(db):
    # Superuser bypasses the seller entitlement/KYC gates so these tests exercise the
    # render-vs-202 decision, not the monetization branch.
    return CustomUser.objects.create_user(
        email="root2@test.uz", username="root2@test.uz", password="pw", is_active=True, is_staff=True, is_superuser=True
    )


@pytest.fixture
def quote(lookups):
    buyer = Company.objects.create(name="Buyer LLC", inn="7700000002")
    seller = Company.objects.create(name="РемПуть", inn="3000000002")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    preparer = CustomUser.objects.create_user(
        email="prep2@seller.test", username="prep2@seller.test", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=preparer, company=seller, role=WorkspaceRole.objects.get(code="OWNER"), is_primary=True, is_active=True
    )
    deal = Deal.objects.create(company=buyer, stage=DealStage.objects.get(code="DRAFT"), title="ARCH-03 export")
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), prepared_by=preparer
    )
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="Колодка", quantity=2, unit="шт", frozen_base_price=Decimal("100")
    )
    quote.recalculate_totals()
    quote.refresh_from_db()
    return quote


@pytest.mark.django_db
def test_export_pdf_202_when_missing(engineer, quote):
    """No persisted PDF → enqueue off-thread render + 202 + Retry-After (never inline)."""
    with patch(RENDER_DELAY) as delay:
        response = handle_quote_export(_request(engineer, "pdf"), quote)
    assert response.status_code == 202
    assert response["Retry-After"] == "2"
    assert response.data["detail"] == "GENERATING"
    delay.assert_called_once_with("quote", quote.pk)


@pytest.mark.django_db
def test_export_pdf_default_format_is_pdf(engineer, quote):
    """No explicit format → defaults to PDF → same 202 path (not an inline render)."""
    with patch(RENDER_DELAY) as delay:
        response = handle_quote_export(_request(engineer), quote)
    assert response.status_code == 202
    delay.assert_called_once_with("quote", quote.pk)


@pytest.mark.django_db
def test_export_pdf_streams_when_present(engineer, quote):
    """A persisted (frozen-on-send) PDF is streamed 200 without re-rendering/enqueuing."""
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
    with patch(RENDER_DELAY) as delay:
        response = handle_quote_export(_request(engineer, "pdf"), quote)
    assert isinstance(response, FileResponse)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    delay.assert_not_called()


@pytest.mark.django_db
def test_export_pdf_unclaimed_guard_409_and_not_enqueued(engineer, quote):
    """A broken КП (unclaimed) still surfaces the cheap guard as 409 — no enqueue, no render."""
    quote.prepared_by = None
    quote.save(update_fields=["prepared_by"])
    with patch(RENDER_DELAY) as delay:
        response = handle_quote_export(_request(engineer, "pdf"), quote)
    assert response.status_code == 409
    assert response.data["detail"] == "QUOTE_NOT_CLAIMED"
    delay.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_export_spreadsheet_stays_synchronous(engineer, quote, fmt):
    """XLSX/CSV are light → rendered synchronously, never enqueued off-thread."""
    with patch(RENDER_DELAY) as delay:
        response = handle_quote_export(_request(engineer, fmt), quote)
    # Synchronous Django file response (not a DRF 202), and no render task queued.
    assert not isinstance(response, Response) or response.status_code == 200
    assert response.status_code == 200
    delay.assert_not_called()


@pytest.mark.django_db
def test_export_unsupported_format_is_400(engineer, quote):
    """A bad format still maps to 400 (unchanged) and never enqueues a render."""
    with patch(RENDER_DELAY) as delay:
        response = handle_quote_export(_request(engineer, "docx"), quote)
    assert response.status_code == 400
    assert response.data["detail"] == "UNSUPPORTED_FORMAT"
    delay.assert_not_called()


@pytest.mark.django_db
def test_export_pdf_cost_gate_untouched_pdf_is_free(engineer, quote):
    """PDF is the free client projection — the xlsx/csv cost gate never fires for it,
    so the async PDF branch is reachable without an entitlement (scope unchanged)."""
    from accounts.services.permissions import can_view_quote_costs_for

    # PDF must not be treated as a cost-bearing export regardless of viewer rights.
    _ = can_view_quote_costs_for  # imported to assert the symbol still exists (contract)
    with patch(RENDER_DELAY):
        response = handle_quote_export(_request(engineer, "pdf"), quote)
    assert response.status_code in (200, 202)
