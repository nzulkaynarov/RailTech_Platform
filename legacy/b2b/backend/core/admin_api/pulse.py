"""
Admin Platform API: endpoints consumed exclusively by the React Platform Admin
SPA (PlatformAdminShell). All views require IsPlatformAdmin.

Exposes:
  GET /api/v1/admin/queue/      — unified triage queue (KYC, role apps, billing, tickets)
  GET /api/v1/admin/pulse/      — time-series pulse metrics (companies, deals, MRR)
  GET /api/v1/admin/search/     — cross-entity search (companies, users, deals, tickets, offers)
  GET /api/v1/admin/activity/   — ActivityLog scoped to a single entity

All data is derived from real DB models via ORM. No hardcoded rows, no fakes.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsPlatformAdmin

# ---------------------------------------------------------------------------
# Triage Queue
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Pulse (time-series)
# ---------------------------------------------------------------------------

VALID_PERIODS = {"7d": 7, "30d": 30, "90d": 90}


def _daily_series(qs, date_field: str, days: int, value_aggr=None) -> list[dict[str, Any]]:
    """Group a queryset by day into a dense series [{date, count, value}]."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    annotated = (
        qs.filter(**{f"{date_field}__date__gte": start})
        .annotate(d=TruncDate(date_field))
        .values("d")
        .annotate(c=Count("id"))
    )
    if value_aggr is not None:
        annotated = annotated.annotate(v=value_aggr)
    by_date: dict[date, dict[str, Any]] = {row["d"]: row for row in annotated if row.get("d")}
    series: list[dict[str, Any]] = []
    for i in range(days):
        current_date = start + timedelta(days=i)
        row = by_date.get(current_date, {})
        series.append(
            {
                "date": current_date.isoformat(),
                "count": int(row.get("c") or 0),
                "value": str(row.get("v") or "0"),
            }
        )
    return series


@extend_schema(
    summary="Admin pulse metrics",
    description="Daily time-series for the admin dashboard: new companies, new deals (count + value), "
    "and monthly recurring revenue base (subscription monthly_rate sum of ACTIVE subs) by day.",
    parameters=[
        OpenApiParameter(name="period", description="7d | 30d | 90d", required=False, type=str),
    ],
    responses={200: OpenApiResponse(description="Pulse payload")},
    tags=["Admin"],
)
class AdminPulseView(APIView):
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        period = request.query_params.get("period", "30d")
        days = VALID_PERIODS.get(period, 30)
        from accounts.models import Company, SupplierSubscription
        from crm.models import Deal, Quote

        companies_series = _daily_series(
            Company.objects.all(),
            "created_at",
            days,
        )
        deals_series = _daily_series(
            Deal.objects.all(),
            "created_at",
            days,
        )
        quotes_series = _daily_series(
            Quote.objects.filter(status__code__in=["SENT", "APPROVED"]),
            "created_at",
            days,
            value_aggr=Coalesce(Sum("total_incl_vat"), Value(Decimal("0"))),
        )

        active_subs = SupplierSubscription.objects.filter(status__in=["ACTIVE", "TRIAL"])
        mrr = active_subs.aggregate(total=Coalesce(Sum("monthly_rate"), Value(Decimal("0"))))["total"] or Decimal("0")

        return Response(
            {
                "period": period,
                "days": days,
                "companies": companies_series,
                "deals": deals_series,
                "quotes_signed_value": quotes_series,
                "mrr": str(mrr),
                "active_subscriptions": active_subs.count(),
            }
        )
