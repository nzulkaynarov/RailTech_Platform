"""Contract document counterparty — the «Поставщик» party on the договор PDF must name
the REAL seller (its CompanyDocumentProfile legal_name, else the Company name), never the
hardcoded platform identity «ООО «RailTech»» (audit F8).

Renders crm/contract_pdf.html directly (no WeasyPrint) with the same context
_render_contract_pdf builds, and also covers the service resolver _quote_seller_company
(seller derived from the quote's owner, not a fragile preparer-membership lookup).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.template.loader import render_to_string

from accounts.models import Company, CompanyDocumentProfile, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.quotes import _quote_seller_company, _seller_document_profile


@pytest.fixture
def scenario(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})

    buyer = Company.objects.create(name="Покупатель LLC", inn="7700000001", legal_address="г. Ташкент, ул. 1")
    seller = Company.objects.create(name="ООО РельсМаш Поставка", inn="3000000001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    preparer = CustomUser.objects.create_user(
        email="prep@seller.test", username="prep@seller.test", password="pw", is_active=True
    )
    CompanyMember.objects.create(
        user=preparer, company=seller, role=WorkspaceRole.objects.get(code="OWNER"), is_primary=True, is_active=True
    )
    deal = Deal.objects.create(company=buyer, stage=DealStage.objects.get(code="DRAFT"), title="Contract brand test")
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), prepared_by=preparer
    )
    QuoteItem.objects.create(quote=quote, imported_raw_name="Колодка", quantity=2, frozen_base_price=Decimal("100"))
    quote.recalculate_totals()
    return buyer, seller, quote


def _render(quote, buyer, supplier, profile):
    # Mirrors the context _render_contract_pdf builds; `contract` is a light dict (Django
    # templates resolve {{ contract.number }} against dict keys) so we don't need the full
    # Contract row to assert the party block.
    contract = {
        "number": "CT-2026-00001",
        "created_at": date(2026, 7, 2),
        "total_amount": Decimal("240.00"),
        "notes": "",
    }
    return render_to_string(
        "crm/contract_pdf.html",
        {
            "contract": contract,
            "deal": quote.deal,
            "company": buyer,
            "seller": supplier,
            "seller_profile": profile,
            "quote": quote,
            "items": quote.items.all(),
        },
    )


@pytest.mark.django_db
def test_seller_company_named_not_platform(scenario):
    buyer, seller, quote = scenario
    # The service resolves the seller from the quote's owner (the fix).
    assert _quote_seller_company(quote).id == seller.id
    html = _render(quote, buyer, seller, None)
    assert "ООО РельсМаш Поставка" in html
    assert "3000000001" in html  # ИНН
    # The old hardcoded platform counterparty must NEVER appear on a real contract.
    assert "«RailTech»" not in html
    assert "ООО «RailTech»" not in html


@pytest.mark.django_db
def test_seller_profile_legal_name_and_requisites(scenario):
    buyer, seller, quote = scenario
    CompanyDocumentProfile.objects.create(
        company=seller,
        legal_name="ООО «РельсМаш Поставка и Ко»",
        inn="3001112223",
        legal_address="г. Самарканд, пр. Мира 5",
        bank_details="р/с 2020 8000 ... МФО 00014",
    )
    profile = _seller_document_profile(seller)
    assert profile is not None
    html = _render(quote, buyer, seller, profile)
    assert "ООО «РельсМаш Поставка и Ко»" in html
    assert "3001112223" in html
    assert "р/с 2020 8000 ... МФО 00014" in html
    assert "«RailTech»" not in html
