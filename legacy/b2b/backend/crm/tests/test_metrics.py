"""Tests for the time-to-first-КП wedge metric (ADR-0006 Move 4)."""

from datetime import timedelta

import pytest

from accounts.models import Company
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteStatus
from crm.services.metrics import time_to_first_quote_stats


@pytest.fixture
def base(db):
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 10})
    buyer = Company.objects.create(name="Buyer", inn="1110000001")
    seller = Company.objects.create(name="Seller", inn="2220000001")
    other = Company.objects.create(name="Other", inn="2220000002")
    return {"buyer": buyer, "seller": seller, "other": other}


def _routed_deal(base):
    deal = Deal.objects.create(title="RFQ", company=base["buyer"], stage=DealStage.objects.get(code="RFQ_OPEN"))
    routing = DealSellerRouting.objects.create(deal=deal, seller_company=base["seller"])
    return deal, routing


def _sent_quote(deal, seller, hours_after_routing, routed_at, version=1):
    return Quote.objects.create(
        deal=deal,
        version=version,
        seller_company=seller,
        status=QuoteStatus.objects.get(code="SENT"),
        frozen_at=routed_at + timedelta(hours=hours_after_routing),
    )


def test_metric_hours_from_routed_to_first_sent(base):
    deal, routing = _routed_deal(base)
    _sent_quote(deal, base["seller"], 5, routing.routed_at)
    stats = time_to_first_quote_stats(seller_company_ids=[base["seller"].id])
    assert stats["sample_size"] == 1
    assert stats["median_hours"] == 5.0 and stats["avg_hours"] == 5.0


def test_uses_first_sent_quote_not_later_revisions(base):
    deal, routing = _routed_deal(base)
    _sent_quote(deal, base["seller"], 3, routing.routed_at, version=1)
    _sent_quote(deal, base["seller"], 9, routing.routed_at, version=2)  # later revision — ignored
    stats = time_to_first_quote_stats(seller_company_ids=[base["seller"].id])
    assert stats["sample_size"] == 1 and stats["median_hours"] == 3.0


def test_scoped_to_seller_excludes_others(base):
    deal, routing = _routed_deal(base)
    _sent_quote(deal, base["seller"], 4, routing.routed_at)
    # scope to a DIFFERENT seller → no sample
    stats = time_to_first_quote_stats(seller_company_ids=[base["other"].id])
    assert stats["sample_size"] == 0 and stats["median_hours"] == 0.0


def test_platform_wide_aggregates_median(base):
    d1, r1 = _routed_deal(base)
    _sent_quote(d1, base["seller"], 2, r1.routed_at)
    d2 = Deal.objects.create(title="RFQ2", company=base["buyer"], stage=DealStage.objects.get(code="RFQ_OPEN"))
    r2 = DealSellerRouting.objects.create(deal=d2, seller_company=base["seller"])
    _sent_quote(d2, base["seller"], 8, r2.routed_at)
    stats = time_to_first_quote_stats()  # platform-wide
    assert stats["sample_size"] == 2 and stats["median_hours"] == 5.0  # (2+8)/2
    assert stats["fastest_hours"] == 2.0 and stats["slowest_hours"] == 8.0


def test_empty_returns_zeros(base):
    assert time_to_first_quote_stats(seller_company_ids=[base["seller"].id])["sample_size"] == 0
