from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter
from django.db.models import Count, Sum, Subquery, OuterRef
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from core.permissions import IsPlatformAdmin
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
            name='period',
            description='Analytics period (7d, 30d, 90d). Default: 30d',
            type=str,
            location=OpenApiParameter.QUERY,
            enum=['7d', '30d', '90d'],
        ),
    ],
    responses={200: OpenApiResponse(description="Dashboard analytics data")},
    tags=['Analytics'],
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

        # B2B data isolation
        is_staff = request.user.is_platform_admin
        if is_staff:
            user_company_ids = None
        else:
            user_company_ids = list(
                request.user.memberships.filter(is_active=True)
                .values_list('company_id', flat=True)
            )

        period = request.query_params.get('period', '30d')
        cache_key = f'dashboard_analytics_{period}_{request.user.pk}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        period_start = self._resolve_period_start(period)

        # Get deals -- scoped to user's companies for non-staff
        all_deals = Deal.objects.all()
        if user_company_ids is not None:
            all_deals = all_deals.filter(company_id__in=user_company_ids)
        period_deals = all_deals.filter(created_at__gte=period_start)

        # Previous period for comparison
        prev_period_start = period_start - (timezone.now() - period_start)
        prev_period_deals = Deal.objects.filter(
            created_at__gte=prev_period_start, created_at__lt=period_start,
        )
        if user_company_ids is not None:
            prev_period_deals = prev_period_deals.filter(company_id__in=user_company_ids)

        volume_kpis = self._get_volume_kpis(period_deals, prev_period_deals, all_deals)
        catalog_kpis = self._get_catalog_kpis(period_start)
        client_kpis = self._get_client_kpis(period_start)
        counterparties = self._get_counterparties()
        completion = self._get_completion_stats(user_company_ids)
        buyer_stats = self._get_buyer_stats(all_deals)

        data = {
            **volume_kpis,
            **catalog_kpis,
            **client_kpis,
            'deals_by_month': self._get_deals_by_month(all_deals),
            'activity_by_day': self._get_activity_by_day(user_company_ids),
            'top_products': self._get_top_products(user_company_ids=user_company_ids),
            'counterparties': counterparties,
            'request_completion': completion['request_completion'],
            'request_completion_goal': 80,
            **buyer_stats,
        }
        cache.set(cache_key, data, 60)
        return Response(data)

    @staticmethod
    def _resolve_period_start(period: str):
        """Convert period string (7d/30d/90d) to a start datetime."""
        days_map = {'7d': 7, '30d': 30, '90d': 90}
        days = days_map.get(period, 30)
        return timezone.now() - timedelta(days=days)

    def _get_volume_kpis(self, period_deals, prev_period_deals, all_deals) -> dict:
        """Compute deals volume and active request KPIs with period-over-period change."""
        latest_quote = Quote.objects.filter(
            deal=OuterRef('pk')
        ).order_by('-version').values('total_incl_vat')[:1]

        current_volume = period_deals.annotate(
            deal_value=Subquery(latest_quote)
        ).aggregate(total=Sum('deal_value'))['total'] or Decimal('0')
        prev_volume = prev_period_deals.annotate(
            deal_value=Subquery(latest_quote)
        ).aggregate(total=Sum('deal_value'))['total'] or Decimal('0')

        current_active = all_deals.exclude(
            stage__code__in=['CLOSED_WON', 'CLOSED_LOST']
        ).count()
        prev_active = prev_period_deals.exclude(
            stage__code__in=['CLOSED_WON', 'CLOSED_LOST']
        ).count()

        return {
            'deals_volume': float(current_volume),
            'deals_volume_change': self._calculate_percentage_change(prev_volume, current_volume),
            'active_requests': current_active,
            'active_requests_change': self._calculate_percentage_change(
                prev_active if prev_active > 0 else current_active, current_active,
            ),
        }

    def _get_catalog_kpis(self, period_start) -> dict:
        """Compute catalog item counts with period-over-period change."""
        from catalog.models import Product
        published_products = Product.objects.filter(status__code='PUBLISHED').count()
        prev_published = Product.objects.filter(
            status__code='PUBLISHED', created_at__lt=period_start,
        ).count()
        return {
            'catalog_items': published_products,
            'catalog_items_change': self._calculate_percentage_change(prev_published, published_products),
        }

    def _get_client_kpis(self, period_start) -> dict:
        """Compute client counts with period-over-period change."""
        from accounts.models import Company, CompanyType
        client_type = CompanyType.objects.filter(code='CLIENT').first()
        if client_type:
            current_clients = Company.objects.filter(types=client_type).distinct().count()
            prev_clients = current_clients - Company.objects.filter(
                types=client_type, created_at__gte=period_start,
            ).distinct().count()
        else:
            current_clients = prev_clients = 0
        return {
            'clients_count': current_clients,
            'clients_count_change': self._calculate_percentage_change(prev_clients, current_clients),
        }

    @staticmethod
    def _get_counterparties() -> dict:
        """Breakdown of companies by type."""
        from accounts.models import Company, CompanyType
        result = {}
        for code, key in [('MANUFACTURER', 'manufacturers'), ('CLIENT', 'buyers'), ('SUPPLIER', 'intermediaries')]:
            ct = CompanyType.objects.filter(code=code).first()
            result[key] = Company.objects.filter(types=ct).count() if ct else 0
        return result

    @staticmethod
    def _get_completion_stats(user_company_ids) -> dict:
        """Compute request completion percentage."""
        quotes_qs = Quote.objects.all()
        if user_company_ids is not None:
            quotes_qs = quotes_qs.filter(deal__company_id__in=user_company_ids)
        completed = quotes_qs.filter(status__code__in=['APPROVED', 'SENT']).count()
        total = quotes_qs.count()
        pct = (completed / total * 100) if total > 0 else 0
        return {'request_completion': round(pct, 1)}

    @staticmethod
    def _get_buyer_stats(all_deals) -> dict:
        """Buyer-specific stage counts."""
        return {
            'deals_in_progress': all_deals.filter(stage__code__in=['SOURCING', 'CALCULATING']).count(),
            'quotes_received': all_deals.filter(stage__code='QUOTE_SENT').count(),
            'deals_completed': all_deals.filter(stage__code__in=['CLOSED_WON', 'CONTRACT_SIGNED']).count(),
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
            .annotate(month=TruncMonth('created_at'))
            .values('month')
            .annotate(
                count=Count('id'), value=Sum('quotes__total_incl_vat')
            )
            .order_by('month')
        )

        result = []
        for item in monthly_deals:
            month_val = item.get('month')
            result.append({
                'month': month_val.strftime('%Y-%m') if month_val else '',
                'count': item['count'],
                'value': float(item.get('value') or 0),
            })
        return result

    def _get_activity_by_day(self, user_company_ids=None):
        """Get activity aggregated by day for the last 30 days."""
        from django.db.models.functions import TruncDate
        from crm.models import ActivityLog

        thirty_days_ago = timezone.now() - timedelta(days=30)
        qs = ActivityLog.objects.filter(timestamp__gte=thirty_days_ago)
        if user_company_ids is not None:
            qs = qs.filter(user__memberships__company_id__in=user_company_ids)
        daily_activity = (
            qs.annotate(day=TruncDate('timestamp'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )

        result = []
        for item in daily_activity:
            day_val = item.get('day')
            result.append({
                'day': day_val.strftime('%a') if day_val else '',
                'count': item['count'],
            })
        return result

    def _get_top_products(self, limit=5, user_company_ids=None):
        """Get top products by deal frequency, scoped to user's companies."""
        from catalog.models import Product

        qs = Product.objects.select_related('category')
        if user_company_ids is not None:
            qs = qs.filter(quote_items__quote__deal__company_id__in=user_company_ids)
        top = qs.annotate(
            deal_count=Count('quote_items', distinct=True)
        ).order_by('-deal_count')[:limit]

        return [
            {
                'id': str(p.id),
                'name': p.name,
                'quantity': p.deal_count,
                'category': p.category.name if p.category else '',
            }
            for p in top
        ]


@extend_schema(
    summary="CRM analytics",
    description="Aggregated CRM analytics data. Manager/Admin only.",
    responses={200: OpenApiResponse(description="CRM analytics data")},
    tags=['Analytics'],
)
class CRMAnalyticsView(APIView):
    """CRM analytics endpoint for managers and admins."""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from crm.services import get_crm_analytics_data
        data = get_crm_analytics_data()
        return Response(data)
