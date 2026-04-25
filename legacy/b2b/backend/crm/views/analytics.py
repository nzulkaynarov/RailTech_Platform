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
        from catalog.models import Product
        from accounts.models import Company

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

        # Calculate period start date
        if period == '30d':
            period_start = timezone.now() - timedelta(days=30)
        elif period == '7d':
            period_start = timezone.now() - timedelta(days=7)
        elif period == '90d':
            period_start = timezone.now() - timedelta(days=90)
        else:
            period_start = timezone.now() - timedelta(days=30)

        # Get deals -- scoped to user's companies for non-staff
        all_deals = Deal.objects.all()
        if user_company_ids is not None:
            all_deals = all_deals.filter(company_id__in=user_company_ids)
        period_deals = all_deals.filter(created_at__gte=period_start)

        # Get previous period deals for comparison (scoped same as all_deals)
        prev_period_start = period_start - (timezone.now() - period_start)
        prev_period_deals = Deal.objects.filter(
            created_at__gte=prev_period_start,
            created_at__lt=period_start
        )
        if user_company_ids is not None:
            prev_period_deals = prev_period_deals.filter(company_id__in=user_company_ids)

        # Calculate deals volume via latest quote's total_incl_vat
        latest_quote = Quote.objects.filter(
            deal=OuterRef('pk')
        ).order_by('-version').values('total_incl_vat')[:1]

        current_volume = period_deals.annotate(
            deal_value=Subquery(latest_quote)
        ).aggregate(total=Sum('deal_value'))['total'] or Decimal('0')
        prev_volume = prev_period_deals.annotate(
            deal_value=Subquery(latest_quote)
        ).aggregate(total=Sum('deal_value'))['total'] or Decimal('0')
        volume_change = self._calculate_percentage_change(
            prev_volume, current_volume
        )

        # Active requests (not closed)
        current_active = all_deals.exclude(
            stage__code__in=['CLOSED_WON', 'CLOSED_LOST']
        ).count()
        prev_active = prev_period_deals.exclude(
            stage__code__in=['CLOSED_WON', 'CLOSED_LOST']
        ).count()
        active_change = self._calculate_percentage_change(
            prev_active if prev_active > 0 else current_active,
            current_active
        )

        # Catalog items
        published_products = Product.objects.filter(
            status__code='PUBLISHED'
        ).count()
        prev_published = Product.objects.filter(
            status__code='PUBLISHED',
            created_at__lt=period_start
        ).count()
        catalog_change = self._calculate_percentage_change(
            prev_published, published_products
        )

        # Clients count
        from accounts.models import CompanyType
        client_type = CompanyType.objects.filter(code='CLIENT').first()
        if client_type:
            current_clients = Company.objects.filter(
                types=client_type
            ).distinct().count()
            prev_clients = current_clients - Company.objects.filter(
                types=client_type,
                created_at__gte=period_start
            ).distinct().count()
        else:
            current_clients = 0
            prev_clients = 0
        clients_change = self._calculate_percentage_change(
            prev_clients, current_clients
        )

        # Deals by month (last 6 months)
        deals_by_month = self._get_deals_by_month(all_deals)

        # Activity by day (last 30 days) -- scoped to user's companies
        activity_by_day = self._get_activity_by_day(user_company_ids)

        # Top products by deal frequency -- scoped to user's companies
        top_products = self._get_top_products(user_company_ids=user_company_ids)

        # Counterparties breakdown
        manufacturer_type = CompanyType.objects.filter(
            code='MANUFACTURER'
        ).first()
        supplier_type = CompanyType.objects.filter(code='SUPPLIER').first()

        counterparties = {
            'manufacturers': (
                Company.objects.filter(types=manufacturer_type).count()
                if manufacturer_type else 0
            ),
            'buyers': (
                Company.objects.filter(types=client_type).count()
                if client_type else 0
            ),
            'intermediaries': (
                Company.objects.filter(types=supplier_type).count()
                if supplier_type else 0
            ),
        }

        # Request completion percentage (scoped)
        quotes_qs = Quote.objects.all()
        if user_company_ids is not None:
            quotes_qs = quotes_qs.filter(deal__company_id__in=user_company_ids)
        completed_quotes = quotes_qs.filter(
            status__code__in=['APPROVED', 'SENT']
        ).count()
        total_quotes = quotes_qs.count()
        completion_percentage = (
            (completed_quotes / total_quotes * 100)
            if total_quotes > 0 else 0
        )

        # Buyer-specific stats
        deals_in_progress = all_deals.filter(
            stage__code__in=['SOURCING', 'CALCULATING']
        ).count()
        quotes_received = all_deals.filter(
            stage__code='QUOTE_SENT'
        ).count()
        deals_completed = all_deals.filter(
            stage__code__in=['CLOSED_WON', 'CONTRACT_SIGNED']
        ).count()

        data = {
            'deals_volume': float(current_volume),
            'deals_volume_change': volume_change,
            'active_requests': current_active,
            'active_requests_change': active_change,
            'catalog_items': published_products,
            'catalog_items_change': catalog_change,
            'clients_count': current_clients,
            'clients_count_change': clients_change,
            'deals_by_month': deals_by_month,
            'activity_by_day': activity_by_day,
            'top_products': top_products,
            'counterparties': counterparties,
            'request_completion': round(completion_percentage, 1),
            'request_completion_goal': 80,
            'deals_in_progress': deals_in_progress,
            'quotes_received': quotes_received,
            'deals_completed': deals_completed,
        }
        cache.set(cache_key, data, 60)
        return Response(data)

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
