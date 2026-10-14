"""P1 unified document base — all four seller-issued PDFs extend crm/_document_base.html and
render the SAME branded chrome (brand header, accent, @page page-counter footer) from the
seller's CompanyDocumentProfile. Invoice + act — which had NO branding at all before — now
carry the seller's identity and accent, so the four documents read as one product.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.template.loader import render_to_string

from accounts.models import Company, CompanyDocumentProfile


def _brand(seller):
    profile = CompanyDocumentProfile.objects.create(
        company=seller, legal_name="ООО «Бренд Тест»", inn="3009998887", accent_color="#0a7d55"
    )
    return {"seller": seller, "seller_profile": profile, "seller_logo_url": None}


@pytest.mark.django_db
def test_invoice_and_act_extend_base_and_brand():
    seller = Company.objects.create(name="Seller Co", inn="3000000009")
    buyer = Company(name="Buyer Co", inn="7700000009")
    brand = _brand(seller)

    invoice_html = render_to_string(
        "crm/invoice_pdf.html",
        {
            "invoice": {
                "number": "INV-1",
                "issued_at": date(2026, 7, 8),
                "due_date": date(2026, 7, 20),
                "subtotal_excl_vat": Decimal("100.00"),
                "vat_amount": Decimal("12.00"),
                "total_incl_vat": Decimal("112.00"),
                "notes": "",
            },
            "items": [],
            "company": buyer,
            **brand,
        },
    )
    act_html = render_to_string(
        "crm/act_pdf.html",
        {
            "act": {
                "number": "ACT-1",
                "issued_at": date(2026, 7, 8),
                "deal_id": 1,
                "contract": None,
                "invoice": None,
                "total_amount": Decimal("112.00"),
            },
            "invoice": None,
            "company": buyer,
            **brand,
        },
    )

    for html, label in [(invoice_html, "invoice"), (act_html, "act")]:
        # Base chrome: the @page page-counter footer proves the doc extends the shared base.
        assert "counter(page)" in html, f"{label} does not extend the shared base"
        # Seller branding now present (was absent before P1).
        assert "ООО «Бренд Тест»" in html, f"{label} missing seller legal_name"
        assert "#0a7d55" in html, f"{label} missing seller accent color"
        # The old prototype navy hardcode is gone.
        assert "#1a1a2e" not in html, f"{label} still uses the legacy hardcoded palette"
