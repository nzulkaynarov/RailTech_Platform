"""Wedge metric — time-to-first-КП (ADR-0006 Move 4). Rule 8 service.

THE wedge KPI (BUSINESS §3.3 «время от запроса до первого КП»): how fast the back office turns a
заявка into a sent КП. Measured per deal as (first sent quote's frozen_at) − (deal.created_at — the
moment the request entered ERP), aggregated to median / avg / p90 so the team can watch the loop get
faster as AI assist lands. Read-only analytics. The seller of every deal is the own company, so the
sample is per deal (the per-seller routing anchor was removed in M1-ERP-02 wave 3).
"""

import statistics
from datetime import timedelta
from typing import Optional

from django.db.models import F, Min
from django.utils import timezone

from ..models import Quote

_EMPTY_STATS = {
    "sample_size": 0,
    "median_hours": 0.0,
    "avg_hours": 0.0,
    "p90_hours": 0.0,
    "fastest_hours": 0.0,
    "slowest_hours": 0.0,
}


def _percentile(sorted_vals, pct: float) -> float:
    """Nearest-rank percentile on an already-sorted list (pct in 0..100)."""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def time_to_first_quote_stats(seller_company_ids: Optional[list] = None, since_days: Optional[int] = None) -> dict:
    """Hours from the request entering ERP → first КП sent, per deal. Optionally scoped to a set of
    seller companies (the own company for staff) and/or a recent window. Returns sample size +
    median/avg/p90/fastest/slowest (hours, rounded). sample_size 0 ⇒ all stats 0."""
    sent = Quote.objects.filter(frozen_at__isnull=False, seller_company__isnull=False)
    if seller_company_ids is not None:
        sent = sent.filter(seller_company_id__in=seller_company_ids)
    if since_days:
        sent = sent.filter(frozen_at__gte=timezone.now() - timedelta(days=since_days))

    # Earliest sent КП per deal — the back office's FIRST quote on that заявка.
    firsts = sent.values("deal_id").annotate(first_sent=Min("frozen_at"), anchor=F("deal__created_at"))
    hours = sorted(
        (row["first_sent"] - row["anchor"]).total_seconds() / 3600.0
        for row in firsts
        if row["anchor"] and row["first_sent"] >= row["anchor"]
    )
    if not hours:
        return dict(_EMPTY_STATS)
    return {
        "sample_size": len(hours),
        "median_hours": round(statistics.median(hours), 1),
        "avg_hours": round(statistics.fmean(hours), 1),
        "p90_hours": round(_percentile(hours, 90), 1),
        "fastest_hours": round(hours[0], 1),
        "slowest_hours": round(hours[-1], 1),
    }
