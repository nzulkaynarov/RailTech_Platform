"""Tests for the time-to-first-КП wedge metric (ADR-0006 Move 4).

Anchor: the moment the request entered ERP (`Deal.created_at`) — the seller of every deal is the own
company, so the per-seller routing anchor is gone (M1-ERP-02 wave 3).
"""

from datetime import timedelta

import pytest

from accounts.models import Company
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.services.metrics import time_to_first_quote_stats


@pytest.fixture
def base(db):
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="SENT", defaults={"name": "Sent", "sort_order": 10})
    buyer = Company.objects.create(name="Buyer", inn="1110000001")
    seller = Company.objects.create(name="Seller", inn="2220000001")
    other = Company.objects.create(name="Other", inn="2220000002")
    return {"buyer": buyer, "seller": seller, "other": other}


def _deal(base, title="RFQ"):
    return Deal.objects.create(title=title, company=base["buyer"], stage=DealStage.objects.get(code="RFQ_OPEN"))


def _sent_quote(deal, seller, hours_after_request, version=1):
    return Quote.objects.create(
        deal=deal,
        version=version,
        seller_company=seller,
        status=QuoteStatus.objects.get(code="SENT"),
        frozen_at=deal.created_at + timedelta(hours=hours_after_request),
    )


def test_metric_hours_from_request_to_first_sent(base):
    deal = _deal(base)
    _sent_quote(deal, base["seller"], 5)
    stats = time_to_first_quote_stats(seller_company_ids=[base["seller"].id])
    assert stats["sample_size"] == 1
    assert stats["median_hours"] == 5.0 and stats["avg_hours"] == 5.0


def test_uses_first_sent_quote_not_later_revisions(base):
    deal = _deal(base)
    _sent_quote(deal, base["seller"], 3, version=1)
    _sent_quote(deal, base["seller"], 9, version=2)  # later revision — ignored
    stats = time_to_first_quote_stats(seller_company_ids=[base["seller"].id])
    assert stats["sample_size"] == 1 and stats["median_hours"] == 3.0


def test_scoped_to_seller_company(base):
    _sent_quote(_deal(base), base["seller"], 4)
    # scope to a company that sent nothing → no sample
    stats = time_to_first_quote_stats(seller_company_ids=[base["other"].id])
    assert stats["sample_size"] == 0 and stats["median_hours"] == 0.0


def test_aggregates_median_across_deals(base):
    _sent_quote(_deal(base, "RFQ1"), base["seller"], 2)
    _sent_quote(_deal(base, "RFQ2"), base["seller"], 8)
    stats = time_to_first_quote_stats()  # everything (administrator)
    assert stats["sample_size"] == 2 and stats["median_hours"] == 5.0  # (2+8)/2
    assert stats["fastest_hours"] == 2.0 and stats["slowest_hours"] == 8.0


def test_quote_sent_before_request_is_ignored(base):
    deal = _deal(base)
    _sent_quote(deal, base["seller"], -1)  # clock skew / imported data — no negative samples
    assert time_to_first_quote_stats()["sample_size"] == 0


def test_empty_returns_zeros(base):
    assert time_to_first_quote_stats(seller_company_ids=[base["seller"].id])["sample_size"] == 0
