from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, OuterRef, Subquery, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.constants import CompanyTypeCode
from core.permissions import IsPlatformAdmin
from crm.constants import DealStageCode, QuoteStatusCode
from crm.models import Deal, Quote


@extend_schema(
    summary="Dashboard analytics",
    description=(
        "Comprehensive dashboard KPIs: deals volume, active requests, "
        "catalog items, clients count, deals by month, activity by day, "
        "top products, counterparties breakdown, and request completion."
    ),
    parameters=[
        OpenApiParameter(
            name="period",
            description="Analytics period (7d, 30d, 90d). Default: 30d",
            type=str,
            location=OpenApiParameter.QUERY,
            enum=["7d", "30d", "90d"],
        ),
    ],
    responses={200: OpenApiResponse(description="Dashboard analytics data")},
    tags=["Analytics"],
)
class DashboardAnalyticsView(APIView):
    """
    Provides comprehensive dashboard analytics with KPIs for the main dashboard.
    GET /api/v1/crm/analytics/dashboard/?period=30d

    Staff sees platform-wide KPIs. Non-staff sees only their companies' data.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.core.cache import cache

        from accounts.services.permissions import (
            acting_context,
            seller_acting_company_ids,
            seller_visible_deal_ids,
        )

        # B2B data isolation. Three mutually-exclusive scopes:
        #   * platform admin            → see-all (company_ids=None, deal_scope=None)
        #   * context-acting seller     → scope by ROUTED DEAL IDS, not buyer-company.
        #     A seller isn't a member of the buyer's deal.company, so the old
        #     company_id__in filter returned ZERO KPIs for a pure seller. Routed
        #     deals are the seller's confidentiality boundary (DealSellerRouting).
        #   * buyer (and dual user in BUYER context) → scope by own company ids (unchanged)
        is_staff = request.user.is_platform_admin
        deal_scope = None if is_staff else seller_visible_deal_ids(request.user, request)
        # The acting seller's OWN company ids — used to scope the catalog-positions KPI to
        # the seller's own products (audit F4: it previously showed the platform-wide count).
        seller_company_ids = None if is_staff else seller_acting_company_ids(request.user, request)
        if is_staff or deal_scope is not None:
            user_company_ids = None
        else:
            user_company_ids = list(
                request.user.memberships.filter(is_active=True).values_list("company_id", flat=True)
            )

        period = request.query_params.get("period", "30d")
        # The acting context MUST be in the cache key (audit M3): catalog_items / clients_count
        # are now context-dependent (seller → own products / routed buyers; buyer → 0), so a dual
        # buyer+seller user switching context within the 60s TTL would otherwise read the other
        # context's numbers.
        cache_key = f"dashboard_analytics_{period}_{acting_context(request) or 'NONE'}_{request.user.pk}"
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        period_start = self._resolve_period_start(period)

        # Get deals -- scoped to routed deal ids (seller) or own companies (buyer).
        all_deals = self._scope_deals(Deal.objects.all(), user_company_ids, deal_scope)
        period_deals = all_deals.filter(created_at__gte=period_start)

        # Previous period for comparison
        prev_period_start = period_start - (timezone.now() - period_start)
        prev_period_deals = self._scope_deals(
            Deal.objects.filter(created_at__gte=prev_period_start, created_at__lt=period_start),
            user_company_ids,
            deal_scope,
        )

        volume_kpis = self._get_volume_kpis(period_deals, prev_period_deals, all_deals)
        catalog_kpis = self._get_catalog_kpis(period_start, is_staff, seller_company_ids)
        client_kpis = self._get_client_kpis(period_start, is_staff, deal_scope)
        counterparties = self._get_counterparties()
        completion = self._get_completion_stats(user_company_ids, deal_scope)
        buyer_stats = self._get_buyer_stats(all_deals)

        data = {
            **volume_kpis,
            **catalog_kpis,
            **client_kpis,
            "deals_by_month": self._get_deals_by_month(all_deals),
            "activity_by_day": self._get_activity_by_day(user_company_ids, deal_scope),
            "top_products": self._get_top_products(user_company_ids=user_company_ids, deal_scope=deal_scope),
            "counterparties": counterparties,
            "request_completion": completion["request_completion"],
            "request_completion_goal": 80,
            **buyer_stats,
        }
        cache.set(cache_key, data, 60)
        return Response(data)

    @staticmethod
    def _scope_deals(deals, user_company_ids, deal_scope):
        """Apply the resolved isolation scope to a Deal queryset.

        deal_scope (a set of routed deal ids) wins for a context-acting seller;
        user_company_ids scopes a buyer to its own companies; both None = see-all
        (platform admin).
        """
        if deal_scope is not None:
            return deals.filter(id__in=deal_scope)
        if user_company_ids is not None:
            return deals.filter(company_id__in=user_company_ids)
        return deals

    @staticmethod
    def _resolve_period_start(period: str):
        """Convert period string (7d/30d/90d) to a start datetime."""
        days_map = {"7d": 7, "30d": 30, "90d": 90}
        days = days_map.get(period, 30)
        return timezone.now() - timedelta(days=days)

    def _get_volume_kpis(self, period_deals, prev_period_deals, all_deals) -> dict:
        """Compute deals volume and active request KPIs with period-over-period change."""
        latest_quote = Quote.objects.filter(deal=OuterRef("pk")).order_by("-version").values("total_incl_vat")[:1]

        current_volume = period_deals.annotate(deal_value=Subquery(latest_quote)).aggregate(total=Sum("deal_value"))[
            "total"
        ] or Decimal("0")
        prev_volume = prev_period_deals.annotate(deal_value=Subquery(latest_quote)).aggregate(total=Sum("deal_value"))[
            "total"
        ] or Decimal("0")

        closed = [DealStageCode.CLOSED_WON, DealStageCode.CLOSED_LOST]
        current_active = all_deals.exclude(stage__code__in=closed).count()
        prev_active = prev_period_deals.exclude(stage__code__in=closed).count()

        return {
            "deals_volume": float(current_volume),
            "deals_volume_change": self._calculate_percentage_change(prev_volume, current_volume),
            "active_requests": current_active,
            "active_requests_change": self._calculate_percentage_change(
                prev_active if prev_active > 0 else current_active,
                current_active,
            ),
        }

    def _get_catalog_kpis(self, period_start, is_staff, seller_company_ids) -> dict:
        """Compute catalog item counts with period-over-period change.

        Scoped to the acting context (audit F4): a platform admin sees the whole PIM; a
        seller sees only ITS OWN published products (Product.owner_company); a buyer has no
        owned catalog (the KPI isn't shown to buyers) so the count is 0.
        """
        from catalog.models import Product

        products = Product.objects.filter(status__code="PUBLISHED")
        if not is_staff:
            products = products.filter(owner_company_id__in=(seller_company_ids or []))
        published_products = products.count()
        prev_published = products.filter(created_at__lt=period_start).count()
        return {
            "catalog_items": published_products,
            "catalog_items_change": self._calculate_percentage_change(prev_published, published_products),
        }

    def _get_client_kpis(self, period_start, is_staff, deal_scope) -> dict:
        """Compute client counts with period-over-period change.

        Scoped to the acting context (audit F4): a platform admin sees every CLIENT company;
        a seller sees only the distinct buyer companies across the deals routed to it; a
        buyer has no "clients" so the count is 0.
        """
        if is_staff:
            from accounts.models import Company, CompanyType

            client_type = CompanyType.objects.filter(code=CompanyTypeCode.CLIENT).first()
            if not client_type:
                return {"clients_count": 0, "clients_count_change": 0}
            current_clients = Company.objects.filter(types=client_type).distinct().count()
            prev_clients = (
                current_clients
                - Company.objects.filter(types=client_type, created_at__gte=period_start).distinct().count()
            )
        elif deal_scope is not None:
            routed = Deal.objects.filter(id__in=deal_scope)
            current_clients = routed.values("company_id").distinct().count()
            # Baseline = distinct buyer companies that ALREADY had a routed deal before the period
            # (audit M4). The earlier "minus in-period-created" math wrongly dropped repeat clients
            # (deals in both periods) from prev, garbling the trend arrow.
            prev_clients = (
                routed.filter(created_at__lt=period_start).values("company_id").distinct().count()
            )
        else:
            current_clients = prev_clients = 0
        return {
            "clients_count": current_clients,
            "clients_count_change": self._calculate_percentage_change(prev_clients, current_clients),
        }

    @staticmethod
    def _get_counterparties() -> dict:
        """Breakdown of companies by type — single query via values().annotate()."""
        from accounts.models import Company

        type_counts = dict(
            Company.objects.filter(
                types__code__in=[CompanyTypeCode.CLIENT, CompanyTypeCode.SUPPLIER],
            )
            .values_list("types__code")
            .annotate(
                count=Count("id", distinct=True),
            )
            .values_list("types__code", "count")
        )
        return {
            "manufacturers": type_counts.get(CompanyTypeCode.MANUFACTURER, 0),
            "buyers": type_counts.get(CompanyTypeCode.CLIENT, 0),
            "intermediaries": type_counts.get(CompanyTypeCode.SUPPLIER, 0),
        }

    @staticmethod
    def _get_completion_stats(user_company_ids, deal_scope=None) -> dict:
        """Compute request completion percentage, scoped to routed deals (seller)
        or own companies (buyer)."""
        quotes_qs = Quote.objects.all()
        if deal_scope is not None:
            quotes_qs = quotes_qs.filter(deal_id__in=deal_scope)
        elif user_company_ids is not None:
            quotes_qs = quotes_qs.filter(deal__company_id__in=user_company_ids)
        completed = quotes_qs.filter(status__code__in=[QuoteStatusCode.APPROVED, QuoteStatusCode.SENT]).count()
        total = quotes_qs.count()
        pct = (completed / total * 100) if total > 0 else 0
        return {"request_completion": round(pct, 1)}

    @staticmethod
    def _get_buyer_stats(all_deals) -> dict:
        """Buyer-specific stage counts."""
        return {
            "deals_in_progress": all_deals.filter(
                stage__code__in=[DealStageCode.SOURCING, DealStageCode.CALCULATING]
            ).count(),
            "quotes_received": all_deals.filter(stage__code=DealStageCode.QUOTE_SENT).count(),
            "deals_completed": all_deals.filter(
                stage__code__in=[DealStageCode.CLOSED_WON, DealStageCode.CONTRACT_SIGNED]
            ).count(),
        }

    def _calculate_percentage_change(self, previous, current):
        """Calculate percentage change between two values."""
        if previous == 0:
            return 0.0
        return round(((current - previous) / abs(previous)) * 100, 1)

    def _get_deals_by_month(self, deals):
        """Get deals aggregated by month for the last 6 months."""
        from django.db.models.functions import TruncMonth

        six_months_ago = timezone.now() - timedelta(days=180)
        monthly_deals = (
            deals.filter(created_at__gte=six_months_ago)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"), value=Sum("quotes__total_incl_vat"))
            .order_by("month")
        )

        result = []
        for item in monthly_deals:
            month_val = item.get("month")
            result.append(
                {
                    "month": month_val.strftime("%Y-%m") if month_val else "",
                    "count": item["count"],
                    "value": float(item.get("value") or 0),
                }
            )
        return result

    def _get_activity_by_day(self, user_company_ids=None, deal_scope=None):
        """Get activity aggregated by day for the last 30 days, scoped to routed
        deals (seller) or own companies (buyer)."""
        from django.db.models.functions import TruncDate

        from crm.models import ActivityLog

        thirty_days_ago = timezone.now() - timedelta(days=30)
        qs = ActivityLog.objects.filter(timestamp__gte=thirty_days_ago)
        if deal_scope is not None:
            qs = qs.filter(entity_type="deal", entity_id__in=deal_scope)
        elif user_company_ids is not None:
            qs = qs.filter(user__memberships__company_id__in=user_company_ids)
        daily_activity = (
            qs.annotate(day=TruncDate("timestamp")).values("day").annotate(count=Count("id")).order_by("day")
        )

        result = []
        for item in daily_activity:
            day_val = item.get("day")
            result.append(
                {
                    # Date (dd.mm), not just the weekday: a sparse 30-day window can contain two
                    # different Fridays, which "%a" rendered as an ambiguous duplicate "Fri/Fri".
                    "day": day_val.strftime("%d.%m") if day_val else "",
                    "count": item["count"],
                }
            )
        return result

    def _get_top_products(self, limit=5, user_company_ids=None, deal_scope=None):
        """Get top products by deal frequency, scoped to routed deals (seller) or
        own companies (buyer)."""
        from catalog.models import Product

        qs = Product.objects.select_related("category")
        if deal_scope is not None:
            qs = qs.filter(quote_items__quote__deal_id__in=deal_scope)
        elif user_company_ids is not None:
            qs = qs.filter(quote_items__quote__deal__company_id__in=user_company_ids)
        top = qs.annotate(deal_count=Count("quote_items", distinct=True)).order_by("-deal_count")[:limit]

        return [
            {
                "id": str(p.id),
                "name": p.name,
                "quantity": p.deal_count,
                "category": p.category.name if p.category else "",
            }
            for p in top
        ]


@extend_schema(
    summary="CRM analytics",
    description="Aggregated CRM analytics data. Manager/Admin only.",
    responses={200: OpenApiResponse(description="CRM analytics data")},
    tags=["Analytics"],
)
class CRMAnalyticsView(APIView):
    """CRM analytics endpoint for managers and admins."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from crm.services import get_crm_analytics_data

        data = get_crm_analytics_data()
        return Response(data)


@extend_schema(
    summary="Time-to-first-КП wedge metric",
    description=(
        "Hours from RFQ routed → first КП sent, aggregated (median/avg/p90). Platform admin sees "
        "the platform-wide loop speed; a seller sees their OWN company's. The headline wedge KPI."
    ),
    parameters=[
        OpenApiParameter(name="since_days", type=int, location=OpenApiParameter.QUERY, required=False),
    ],
    responses={200: OpenApiResponse(description="{sample_size, median_hours, avg_hours, p90_hours, ...}")},
    tags=["Analytics"],
)
class TimeToFirstQuoteView(APIView):
    """ADR-0006 Move 4 wedge metric. GET /api/v1/crm/analytics/time-to-first-quote/?since_days=30"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from accounts.services.permissions import seller_acting_company_ids
        from crm.services.metrics import time_to_first_quote_stats

        is_staff = getattr(request.user, "is_platform_admin", False)
        # Platform admin → whole platform (None). A seller → only their OWN company's КП (never a
        # competitor's). A pure buyer has no seller companies → empty scope → zero sample.
        seller_company_ids = None if is_staff else list(seller_acting_company_ids(request.user, request) or [])
        try:
            since_days = int(request.query_params.get("since_days")) if request.query_params.get("since_days") else None
        except (TypeError, ValueError):
            since_days = None
        data = time_to_first_quote_stats(seller_company_ids=seller_company_ids, since_days=since_days)
        return Response(data)
