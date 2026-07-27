"""КП document branding — the «Поставщик» block renders from the selling company's
CompanyDocumentProfile when present, and falls back to the platform name when absent.

Renders crm/quote_pdf.html directly (no WeasyPrint) with the same context generate_pdf
builds, so we assert the data-driven seller block without binary PDF parsing. Also covers
the service helper _seller_document_profile (empty profile → None fallback).
"""

from decimal import Decimal

import pytest
from django.template.loader import render_to_string

from accounts.models import Company, CompanyDocumentProfile, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.quotes import _seller_document_profile


@pytest.fixture
def lookups(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})


@pytest.fixture
def scenario(lookups):
    buyer = Company.objects.create(name="Покупатель LLC", inn="7700000001", legal_address="г. Ташкент, ул. 1")
    seller = Company.objects.create(name="РемПуть", inn="3000000001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    preparer = CustomUser.objects.create_user(
        email="prep@seller.test", username="prep@seller.test", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=preparer, company=seller, role=WorkspaceRole.objects.get(code="OWNER"), is_primary=True, is_active=True
    )
    deal = Deal.objects.create(company=buyer, stage=DealStage.objects.get(code="DRAFT"), title="Brand test")
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), prepared_by=preparer
    )
    QuoteItem.objects.create(
        quote=quote, imported_raw_name="Колодка", quantity=2, unit="шт", frozen_base_price=Decimal("100")
    )
    quote.recalculate_totals()
    return buyer, seller, quote


def _render(quote, buyer, seller, profile):
    return render_to_string(
        "crm/quote_pdf.html",
        {
            "quote": quote,
            "items": quote.items.all(),
            "company": buyer,
            "seller": seller,
            "seller_profile": profile,
            "seller_logo_url": None,
        },
    )


@pytest.mark.django_db
def test_seller_profile_drives_document(scenario):
    buyer, seller, quote = scenario
    CompanyDocumentProfile.objects.create(
        company=seller,
        legal_name="ООО «РемПуть Логистика»",
        inn="3001112223",
        legal_address="г. Самарканд, пр. Мира 5",
        footer_text="Спасибо за сотрудничество с РемПуть!",
    )
    resolved = _seller_document_profile(seller)
    assert resolved is not None
    html = _render(quote, buyer, seller, resolved)
    assert "ООО «РемПуть Логистика»" in html
    assert "3001112223" in html
    assert "Спасибо за сотрудничество с РемПуть!" in html
    # Platform fallback footer must NOT appear when a profile footer is set.
    assert "Документ сформирован в RailTech B2B Ecosystem" not in html


@pytest.mark.django_db
def test_empty_profile_falls_back(scenario):
    buyer, seller, quote = scenario
    # An auto-created but unfilled profile must resolve to None (clean Company fallback).
    CompanyDocumentProfile.objects.create(company=seller)
    assert _seller_document_profile(seller) is None
    html = _render(quote, buyer, seller, None)
    # Seller Company name (not the branded legal_name) + platform attribution in the footer
    # (print-typography wave: the auto registration footer wraps the attribution with <br>).
    assert "РемПуть" in html
    assert "Документ сформирован" in html and "RailTech B2B Ecosystem" in html


@pytest.mark.django_db
def test_no_seller_uses_platform_name(scenario):
    buyer, _, quote = scenario
    html = _render(quote, buyer, None, None)
    assert "RailTech B2B" in html
    assert "Документ сформирован в RailTech B2B Ecosystem" in html
