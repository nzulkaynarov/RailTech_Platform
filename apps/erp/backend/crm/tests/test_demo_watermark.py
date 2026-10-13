"""КП PDF demo watermark (ADR-0006 Move 4) — the template overlays «ДЕМО …» only when is_demo."""

import pytest
from django.template.loader import render_to_string

from accounts.models import Company
from crm.models import Deal, DealStage, Quote


@pytest.mark.django_db
def test_quote_pdf_demo_watermark_is_conditional():
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    buyer = Company.objects.create(name="Buyer Co", inn="7000000001")
    seller = Company.objects.create(name="Seller Co", inn="7000000002")
    deal = Deal.objects.create(title="d", company=buyer, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(deal=deal, version=1)
    ctx = {
        "quote": quote,
        "items": quote.items.all(),
        "company": buyer,
        "seller": seller,
        "seller_profile": None,
        "seller_logo_url": None,
    }
    on = render_to_string("crm/quote_pdf.html", {**ctx, "is_demo": True})
    off = render_to_string("crm/quote_pdf.html", {**ctx, "is_demo": False})

    assert 'class="demo-watermark"' in on and "не для коммерческого" in on
    assert 'class="demo-watermark"' not in off  # the CSS rule stays; the OVERLAY div must not
