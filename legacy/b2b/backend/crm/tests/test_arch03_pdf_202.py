"""ARCH-03 — authenticated document-PDF endpoints never run WeasyPrint inline.

A missing PDF gets 202 + Retry-After and the idempotent off-thread render task is
enqueued; the cheap render guards still surface synchronously as 409. Covers the КП
generate/download actions, the deal export-pdf action and the shared 202 helper the
billing (contract/invoice/act) downloads reuse.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus

RENDER_DELAY = "crm.tasks.render_document_pdf.delay"


@pytest.fixture
def lookups(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})


@pytest.fixture
def quote(lookups):
    buyer = Company.objects.create(name="Buyer LLC", inn="7700000001")
    seller = Company.objects.create(name="РемПуть", inn="3000000001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    preparer = CustomUser.objects.create_user(
        email="prep@seller.test", username="prep@seller.test", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=preparer, company=seller, role=WorkspaceRole.objects.get(code="OWNER"), is_primary=True, is_active=True
    )
    deal = Deal.objects.create(company=buyer, stage=DealStage.objects.get(code="DRAFT"), title="ARCH-03")
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), prepared_by=preparer
    )
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="Колодка", quantity=2, unit="шт", frozen_base_price=Decimal("100")
    )
    quote.recalculate_totals()
    quote.refresh_from_db()
    return quote


@pytest.fixture
def api(db):
    engineer = CustomUser.objects.create_user(
        email="root@test.uz",
        username="root@test.uz",
        password="pw",
        is_active=True,
        is_staff=True,
        is_superuser=True,
    )
    client = APIClient()
    client.force_authenticate(engineer)
    return client


@pytest.mark.django_db
def test_download_pdf_202_when_missing(api, quote):
    with patch(RENDER_DELAY) as delay:
        response = api.get(f"/api/v1/crm/quotes/{quote.pk}/download-pdf/")
    assert response.status_code == 202
    assert response["Retry-After"] == "2"
    assert response.data["detail"] == "GENERATING"
    delay.assert_called_once_with("quote", quote.pk)


@pytest.mark.django_db
def test_download_pdf_streams_when_present(api, quote):
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
    with patch(RENDER_DELAY) as delay:
        response = api.get(f"/api/v1/crm/quotes/{quote.pk}/download-pdf/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    delay.assert_not_called()


@pytest.mark.django_db
def test_generate_pdf_202_and_clears_stale_file(api, quote):
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 stale"), save=True)
    with patch(RENDER_DELAY) as delay:
        response = api.post(f"/api/v1/crm/quotes/{quote.pk}/generate-pdf/")
    assert response.status_code == 202
    assert response.data["detail"] == "GENERATING"
    quote.refresh_from_db()
    # The stale file reference is dropped so a concurrent download can't serve the
    # outdated render while the task rebuilds it.
    assert not quote.pdf_file
    delay.assert_called_once_with("quote", quote.pk)


@pytest.mark.django_db
def test_generate_pdf_unclaimed_guard_409_and_not_enqueued(api, quote):
    quote.prepared_by = None
    quote.save(update_fields=["prepared_by"])
    with patch(RENDER_DELAY) as delay:
        response = api.post(f"/api/v1/crm/quotes/{quote.pk}/generate-pdf/")
    assert response.status_code == 409
    assert response.data["error"] == "QUOTE_NOT_CLAIMED"
    delay.assert_not_called()


@pytest.mark.django_db
def test_download_pdf_unclaimed_guard_409(api, quote):
    quote.prepared_by = None
    quote.save(update_fields=["prepared_by"])
    with patch(RENDER_DELAY) as delay:
        response = api.get(f"/api/v1/crm/quotes/{quote.pk}/download-pdf/")
    assert response.status_code == 409
    assert response.data["error"] == "QUOTE_NOT_CLAIMED"
    delay.assert_not_called()


@pytest.mark.django_db
def test_deal_export_pdf_202_when_missing(api, quote):
    with patch(RENDER_DELAY) as delay:
        response = api.get(f"/api/v1/crm/deals/{quote.deal_id}/export-pdf/")
    assert response.status_code == 202
    assert response["Retry-After"] == "2"
    delay.assert_called_once_with("quote", quote.pk)


@pytest.mark.django_db
def test_pdf_generating_response_contract():
    """The shared helper (used by contract/invoice/act downloads) enqueues + 202s."""
    from crm.views._pdf import pdf_generating_response

    with patch(RENDER_DELAY) as delay:
        response = pdf_generating_response("invoice", 42)
    assert response.status_code == 202
    assert response["Retry-After"] == "2"
    assert response.data == {"detail": "GENERATING", "retry_after": 2}
    delay.assert_called_once_with("invoice", 42)
