"""PDF freshness — invalidate-on-write for drafts, immutable snapshot after send.

World-pattern split (Odoo for mutable quotations / PandaDoc-DocuSign for sent documents):
  • an UNFROZEN КП's rendered PDF is a cache of its content — any content write (all of which
    funnel through ``recalculate_quote``) clears the file, and the download endpoint lazily
    re-renders the fresh state on next request;
  • a FROZEN КП's file is the immutable snapshot the client received — recalc never clears it
    and the explicit regenerate action refuses with 409 QUOTE_PDF_IMMUTABLE.
"""

from decimal import Decimal

from django.core.files.base import ContentFile
from django.utils import timezone

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services import QuoteCalculationService


@pytest.fixture
def seller_world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="CALCULATING", defaults={"name": "Calc", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    company = Company.objects.create(name="PDF Seller", inn="PDF100")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="pdf@seller.test", username="pdf@seller.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    deal = Deal.objects.create(title="PDF deal", company=None, stage=DealStage.objects.get(code="CALCULATING"))
    DealSellerRouting.objects.create(deal=deal, seller_company=company, assigned_to=user)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=user,
        seller_company=company,
    )
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="Деталь", quantity=2, frozen_base_price=Decimal("1000.00")
    )
    quote.pdf_file.save("cached.pdf", ContentFile(b"%PDF-1.4 cached"), save=True)
    return {"quote": quote, "user": user}


def _api(user):
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ACTIVE_CONTEXT="SELLER",
    )
    return client


def test_content_write_clears_the_cached_pdf_of_a_draft(seller_world):
    """Editing a line funnels into recalculate_quote → the stale file reference is dropped, so
    the next download lazily renders the CURRENT content instead of serving the old prices."""
    quote = seller_world["quote"]
    assert quote.pdf_file

    item = quote.items.first()
    item.quantity = 5
    item.save()  # model save → recalculate_quote (the single choke point)

    quote.refresh_from_db()
    assert not quote.pdf_file


def test_frozen_quote_file_survives_recalc(seller_world):
    """A frozen КП is the client's immutable snapshot — recalc must never clear its file."""
    quote = seller_world["quote"]
    quote.frozen_at = timezone.now()
    quote.save(update_fields=["frozen_at"])

    QuoteCalculationService.recalculate_quote(quote.id)

    quote.refresh_from_db()
    assert quote.pdf_file


def test_explicit_regenerate_refused_on_frozen_quote(seller_world):
    """POST generate-pdf on a frozen КП with an existing file → 409 QUOTE_PDF_IMMUTABLE (a legal
    document must not be silently re-rendered under a newer template)."""
    quote = seller_world["quote"]
    quote.frozen_at = timezone.now()
    quote.save(update_fields=["frozen_at"])

    resp = _api(seller_world["user"]).post(f"/api/v1/crm/quotes/{quote.id}/generate-pdf/")

    assert resp.status_code == 409, resp.content
    assert resp.json()["detail"] == "QUOTE_PDF_IMMUTABLE"
    quote.refresh_from_db()
    assert quote.pdf_file
