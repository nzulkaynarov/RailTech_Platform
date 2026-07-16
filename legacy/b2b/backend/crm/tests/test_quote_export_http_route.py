"""REGRESSION — КП export must survive the full DRF dispatch (the ?format collision).

The bug this locks: `GET /api/v1/crm/quotes/<id>/export/?format=pdf` returned **HTTP 404**
for every format. DRF's URL_FORMAT_OVERRIDE (default `'format'`) hijacks the `?format`
query param during content-negotiation and raises Http404 (no renderer named 'pdf') BEFORE
the view runs — so the seller's export button (PDF / xlsx / csv) was fully dead on prod.
No test caught it because the whole suite drove `export_quote` / `handle_quote_export`
directly, bypassing HTTP dispatch.

The fix renames the query key to `export_format` (which DRF does not reserve). These tests
therefore go through the REAL APIClient dispatch (routing → negotiation → viewset →
get_object → action) — the only layer that reproduces the 404 — and assert that
`?export_format=…` now reaches the view for each format, while the legacy `?format=…` is
still 404'd by DRF (which is exactly why we stopped using it). Export scoping is also
asserted: a seller from another company cannot pull a foreign КП.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    WorkspaceRole,
)
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus

RENDER_DELAY = "crm.tasks.render_document_pdf.delay"


@pytest.fixture
def lookups(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})


def _seller_member(company, email):
    """A can_sell member with a no-permission CompanyRole.

    No `quote.view_cost_margin` → the export is the client-safe projection, so xlsx/csv
    return 200 without tripping the paid cost-export gate (that gate is exercised
    elsewhere; here we only assert the route is reachable per format)."""
    owner = WorkspaceRole.objects.get(code="OWNER")
    role = CompanyRole.objects.create(company=company, name=f"role-{email}", permissions=[])
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user, company=company, role=owner, company_role=role, is_primary=True, is_active=True, can_sell=True
    )
    return user


@pytest.fixture
def seller_setup(lookups):
    """A seller company, its owning member, and a claimed КП on a routed buyer deal.

    A DealSellerRouting row links seller_co to the buyer's deal — that (not deal.company) is
    what makes the заявка/КП visible to the seller through the multi-seller confidentiality
    scope. prepared_by anchors the КП to the seller (claim guard passes → free PDF renders)."""
    buyer_co = Company.objects.create(name="Покупатель", inn="7700000010")
    seller_co = Company.objects.create(name="РемПуть", inn="3000000010")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller_owner = _seller_member(seller_co, "owner@seller.test")
    deal = Deal.objects.create(company=buyer_co, stage=DealStage.objects.get(code="DRAFT"), title="Export HTTP")
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), prepared_by=seller_owner
    )
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="Колодка", quantity=2, unit="шт", frozen_base_price=Decimal("100")
    )
    quote.recalculate_totals()
    quote.refresh_from_db()
    return seller_co, seller_owner, quote


@pytest.fixture
def owner_client(seller_setup):
    _, seller_owner, _ = seller_setup
    client = APIClient()
    client.force_authenticate(seller_owner)
    return client


def _url(quote):
    return f"/api/v1/crm/quotes/{quote.pk}/export/"


@pytest.mark.django_db
def test_export_pdf_http_streams_when_present(owner_client, seller_setup):
    """The core regression: ?export_format=pdf reaches the view (NOT the DRF 404) and, with
    a persisted PDF, streams 200 application/pdf."""
    _, _, quote = seller_setup
    quote.pdf_file.save("kp.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
    response = owner_client.get(_url(quote), {"export_format": "pdf"})
    assert response.status_code == 200, response.status_code
    assert response["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_export_pdf_http_202_when_missing(owner_client, seller_setup):
    """No persisted PDF → the route still lands (not 404): 202 + off-thread render (ARCH-03)."""
    _, _, quote = seller_setup
    with patch(RENDER_DELAY) as delay:
        response = owner_client.get(_url(quote), {"export_format": "pdf"})
    assert response.status_code == 202, response.status_code
    assert response.data["detail"] == "GENERATING"
    delay.assert_called_once_with("quote", quote.pk)


@pytest.mark.django_db
def test_export_xlsx_http_streams(owner_client, seller_setup):
    """?export_format=xlsx reaches the view and streams a spreadsheet (200), not a 404."""
    _, _, quote = seller_setup
    response = owner_client.get(_url(quote), {"export_format": "xlsx"})
    assert response.status_code == 200, response.status_code
    assert "spreadsheetml.sheet" in response["Content-Type"]


@pytest.mark.django_db
def test_export_csv_http_streams(owner_client, seller_setup):
    """?export_format=csv reaches the view and streams CSV (200), not a 404."""
    _, _, quote = seller_setup
    response = owner_client.get(_url(quote), {"export_format": "csv"})
    assert response.status_code == 200, response.status_code
    assert "text/csv" in response["Content-Type"]


@pytest.mark.django_db
def test_legacy_format_param_is_still_404_by_drf(owner_client, seller_setup):
    """Documents WHY the rename was necessary: the old `?format=pdf` is consumed by DRF's
    URL_FORMAT_OVERRIDE and 404s before the view — we deliberately no longer send it."""
    _, _, quote = seller_setup
    response = owner_client.get(_url(quote), {"format": "pdf"})
    assert response.status_code == 404, response.status_code


@pytest.mark.django_db
def test_export_is_scoped_to_owning_company(seller_setup):
    """A seller from ANOTHER company cannot export a foreign КП — the ViewSet queryset scope
    hides it, so get_object 404s (tenant isolation, not the format collision)."""
    _, _, quote = seller_setup
    foreign_co = Company.objects.create(name="ЧужойПоставщик", inn="3000000099")
    foreign_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    foreign_user = _seller_member(foreign_co, "foreign@seller.test")
    foreign_client = APIClient()
    foreign_client.force_authenticate(foreign_user)
    response = foreign_client.get(_url(quote), {"export_format": "xlsx"})
    assert response.status_code == 404, response.status_code
