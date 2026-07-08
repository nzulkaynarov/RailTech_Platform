"""P0 document-correctness fixes (2026-07-08) — the three verified template defects:

  1. INVOICE «Поставщик» must name the REAL seller (its CompanyDocumentProfile legal_name,
     else the Company), NEVER the hardcoded fake platform identity «ООО «RailTech»» /
     ИНН 300000000001 (IRON RULE 1/2 — an invoice is a legal document).
  2. CONTRACT line «Сумма, без НДС» = line_total (price × qty), not the unit price.
  3. Client КП PDF must NOT leak the CBU FX-rate snapshot to the buyer (soft sourcing leak
     on a UZS-canonical client projection).

Templates are rendered directly via render_to_string (no WeasyPrint), mirroring the context
the _render_*_pdf services build — the same approach as test_contract_document_profile.py.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.template.loader import render_to_string

from accounts.models import Company, CompanyDocumentProfile, CustomUser
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus


# ─────────────────────────────────────────────────────────────────────
# 1. Invoice supplier — real seller, never the hardcoded platform identity
# ─────────────────────────────────────────────────────────────────────
def _render_invoice(supplier=None, seller_profile=None):
    invoice = {
        "number": "INV-2026-00001",
        "issued_at": date(2026, 7, 8),
        "due_date": date(2026, 7, 22),
        "subtotal_excl_vat": Decimal("200.00"),
        "vat_amount": Decimal("24.00"),
        "total_incl_vat": Decimal("224.00"),
        "notes": "",
    }
    items = [
        {
            "description": "Колодка тормозная",
            "quantity": 2,
            "unit_price_excl_vat": Decimal("100.00"),
            "line_total_excl_vat": Decimal("200.00"),
        }
    ]
    buyer = Company(name="Покупатель LLC", inn="7700000001", legal_address="г. Ташкент")
    return render_to_string(
        "crm/invoice_pdf.html",
        {"invoice": invoice, "items": items, "company": buyer, "seller": supplier, "seller_profile": seller_profile},
    )


@pytest.mark.django_db
def test_invoice_names_real_seller_not_platform():
    seller = Company.objects.create(name="ООО РельсМаш Поставка", inn="3000000001", legal_address="г. Самарканд")
    html = _render_invoice(supplier=seller)
    assert "ООО РельсМаш Поставка" in html
    assert "3000000001" in html
    # The old hardcoded fake supplier must NEVER appear on a real invoice.
    assert "ООО «RailTech»" not in html
    assert "300000000001" not in html


@pytest.mark.django_db
def test_invoice_prefers_seller_profile_legal_name():
    seller = Company.objects.create(name="Seller Co", inn="3000000001")
    profile = CompanyDocumentProfile.objects.create(
        company=seller,
        legal_name="ООО «РельсМаш и Ко»",
        inn="3001112223",
        legal_address="г. Самарканд, пр. Мира 5",
    )
    html = _render_invoice(supplier=seller, seller_profile=profile)
    assert "ООО «РельсМаш и Ко»" in html
    assert "3001112223" in html
    assert "ООО «RailTech»" not in html


def test_invoice_without_resolvable_seller_shows_dash_not_fake():
    """A manual invoice without a contract can't resolve a seller — show «—», not fake data."""
    html = _render_invoice(supplier=None, seller_profile=None)
    assert "300000000001" not in html
    assert "ООО «RailTech»" not in html


# ─────────────────────────────────────────────────────────────────────
# 2. Contract line sum = price × qty  +  3. КП hides FX rates
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def quote_qty2(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    buyer = Company.objects.create(name="Buyer LLC", inn="7700000002")
    seller = Company.objects.create(name="Seller LLC", inn="3000000002")
    preparer = CustomUser.objects.create_user(email="p2@s.test", username="p2@s.test", password="pw", is_active=True)
    deal = Deal.objects.create(company=buyer, stage=DealStage.objects.get(code="DRAFT"), title="LT")
    quote = Quote.objects.create(deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), prepared_by=preparer)
    QuoteItem.objects.create(quote=quote, imported_raw_name="Колодка", quantity=2, frozen_base_price=Decimal("100"))
    quote.recalculate_totals()
    return buyer, seller, quote


@pytest.mark.django_db
def test_contract_line_sum_is_price_times_qty(quote_qty2):
    buyer, seller, quote = quote_qty2
    item = quote.items.first()
    assert item.quantity == 2
    assert item.line_total == item.final_price_excl_vat * 2  # 200, not 100
    contract = {"number": "CT-2026-00001", "created_at": date(2026, 7, 8), "total_amount": Decimal("224.00"), "notes": ""}
    html = render_to_string(
        "crm/contract_pdf.html",
        {
            "contract": contract,
            "deal": quote.deal,
            "company": buyer,
            "seller": seller,
            "seller_profile": None,
            "quote": quote,
            "items": quote.items.all(),
        },
    )
    # The line total (price × qty = 200) renders; before the fix the sum column showed the
    # unit price (100) and 200 appeared nowhere. Locale-robust: ru L10N renders "200,00".
    assert ("200,00" in html) or ("200.00" in html)


@pytest.mark.django_db
def test_quote_pdf_hides_fx_rate_from_client(quote_qty2):
    buyer, seller, quote = quote_qty2
    quote.fx_snapshot = {"USD": "12500.00"}
    quote.save(update_fields=["fx_snapshot"])
    html = render_to_string(
        "crm/quote_pdf.html",
        {
            "quote": quote,
            "items": quote.items.all(),
            "company": buyer,
            "seller": seller,
            "seller_profile": None,
            "seller_logo_url": None,
            "is_demo": False,
        },
    )
    # No CBU rate note, no rate value — the client only sees the final UZS price.
    assert "Курс ЦБ" not in html
    assert "пересчитаны" not in html
    assert "12500" not in html
