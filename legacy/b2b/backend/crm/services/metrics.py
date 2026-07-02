"""Wedge metric — time-to-first-КП (ADR-0006 Move 4). Rule 8 service.

THE wedge KPI: how fast a routed seller turns a buyer заявка into a sent КП. Measured per routing
as (first sent quote's frozen_at) − (routing.routed_at), aggregated to median / avg / p90 so the
platform (and each seller) can watch the loop get faster as AI assist lands. Read-only analytics.
"""

import statistics
from datetime import timedelta
from typing import Optional

from django.db.models import Min
from django.utils import timezone

from ..models import DealSellerRouting, Quote


def _percentile(sorted_vals, pct: float) -> float:
    """Nearest-rank percentile on an already-sorted list (pct in 0..100)."""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def time_to_first_quote_stats(seller_company_ids: Optional[list] = None, since_days: Optional[int] = None) -> dict:
    """Hours from RFQ routed → first КП sent, per (deal, seller_company). Optionally scoped to a set
    of seller companies and/or a recent window. Returns sample size + median/avg/p90/fastest/slowest
    (hours, rounded). sample_size 0 ⇒ all stats 0."""
    sent = Quote.objects.filter(frozen_at__isnull=False, seller_company__isnull=False)
    if seller_company_ids is not None:
        sent = sent.filter(seller_company_id__in=seller_company_ids)
    if since_days:
        sent = sent.filter(frozen_at__gte=timezone.now() - timedelta(days=since_days))

    # Earliest sent КП per (deal, seller_company) — the seller's FIRST quote on that заявка.
    firsts = list(sent.values("deal_id", "seller_company_id").annotate(first_sent=Min("frozen_at")))
    if not firsts:
        return {
            "sample_size": 0,
            "median_hours": 0.0,
            "avg_hours": 0.0,
            "p90_hours": 0.0,
            "fastest_hours": 0.0,
            "slowest_hours": 0.0,
        }

    # One query for all relevant routings → {(deal_id, seller_company_id): routed_at}.
    pairs = {(f["deal_id"], f["seller_company_id"]) for f in firsts}
    routed_at = {
        (r.deal_id, r.seller_company_id): r.routed_at
        for r in DealSellerRouting.objects.filter(
            deal_id__in={d for d, _ in pairs}, seller_company_id__in={s for _, s in pairs}
        )
    }

    hours = []
    for f in firsts:
        anchor = routed_at.get((f["deal_id"], f["seller_company_id"]))
        if anchor and f["first_sent"] >= anchor:
            hours.append((f["first_sent"] - anchor).total_seconds() / 3600.0)
    if not hours:
        return {
            "sample_size": 0,
            "median_hours": 0.0,
            "avg_hours": 0.0,
            "p90_hours": 0.0,
            "fastest_hours": 0.0,
            "slowest_hours": 0.0,
        }

    hours.sort()
    return {
        "sample_size": len(hours),
        "median_hours": round(statistics.median(hours), 1),
        "avg_hours": round(statistics.fmean(hours), 1),
        "p90_hours": round(_percentile(hours, 90), 1),
        "fastest_hours": round(hours[0], 1),
        "slowest_hours": round(hours[-1], 1),
    }
