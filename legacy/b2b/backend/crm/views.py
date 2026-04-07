from rest_framework import viewsets, status, throttling
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Deal, DealStage, Quote, QuoteItem, Message, ActivityLog
from .serializers import (
    DealListSerializer, DealDetailSerializer, QuoteSerializer, QuoteItemSerializer,
    MessageSerializer, ActivityLogSerializer, LeadSerializer
)
from rest_framework.permissions import IsAuthenticated
from core.permissions import IsManagerOrAdmin, IsOwnerOrManagerOrAdmin
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

# Explicit deal stage transition matrix (FSM)
ALLOWED_STAGE_TRANSITIONS = {
    'DRAFT': ['KYC_PENDING', 'SOURCING', 'CLOSED_LOST'],
    'KYC_PENDING': ['SOURCING', 'CLOSED_LOST'],
    'SOURCING': ['CALCULATING', 'CLOSED_LOST'],
    'CALCULATING': ['QUOTE_SENT', 'SOURCING', 'CLOSED_LOST'],
    'QUOTE_SENT': ['CONTRACT_SIGNED', 'CALCULATING', 'CLOSED_LOST'],
    'CONTRACT_SIGNED': ['CLOSED_WON', 'CLOSED_LOST'],
    'CLOSED_WON': [],   # Terminal state
    'CLOSED_LOST': [],   # Terminal state
}


class DealViewSet(viewsets.ModelViewSet):
    def get_serializer_class(self):
        if self.action == 'list':
            return DealListSerializer
        return DealDetailSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        queryset = Deal.objects.all().select_related(
            'client', 'manager', 'company', 'stage'
        ).prefetch_related('quotes', 'quotes__items')

        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        # B2B Filter: User sees all deals of their active companies
        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(company_id__in=user_company_ids)

    def perform_create(self, serializer):
        # Auto-assign the primary company if not provided
        primary_company = self.request.user.primary_company
        if not primary_company:
            from rest_framework.exceptions import ValidationError
            raise ValidationError(
                {"company": "У вас нет привязанной компании. Заполните профиль компании."}
            )
        deal = serializer.save(client=self.request.user,
                               company=primary_company)

        ActivityLog.objects.create(
            action="Сделка создана",
            detail=(
                f"Пользователь {self.request.user.email} инициировал "
                f"новую сделку #{deal.id} для компании "
                f"{deal.company.name if deal.company else 'N/A'}"
            ),
            user=self.request.user,
            level='INFO'
        )

    @action(detail=True, methods=['post'], url_path='change-stage')
    def change_stage(self, request, pk=None):
        """Change deal stage with FSM validation."""
        deal = self.get_object()
        stage_code = request.data.get('stage_code')
        if not stage_code:
            return Response({'detail': 'stage_code is required.'}, status=status.HTTP_400_BAD_REQUEST)

        new_stage = DealStage.objects.filter(code=stage_code).first()
        if not new_stage:
            return Response({'detail': f'Unknown stage: {stage_code}'}, status=status.HTTP_400_BAD_REQUEST)

        # FSM validation: check allowed transitions
        current_code = deal.stage.code if deal.stage else 'DRAFT'
        allowed = ALLOWED_STAGE_TRANSITIONS.get(current_code, [])
        if stage_code not in allowed:
            return Response(
                {'detail': f'Transition {current_code} → {stage_code} is not allowed. '
                           f'Allowed: {", ".join(allowed) if allowed else "none (terminal state)"}'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        old_stage_name = deal.stage.name if deal.stage else 'N/A'
        deal.stage = new_stage
        deal.save(update_fields=['stage'])

        ActivityLog.objects.create(
            action="Стадия изменена",
            detail=f"Сделка #{deal.id}: {old_stage_name} → {new_stage.name}",
            user=request.user,
            level='INFO'
        )
        serializer = DealDetailSerializer(deal)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='export-pdf')
    def export_pdf(self, request, pk=None):
        """Export PDF of the deal's active quote."""
        deal = self.get_object()
        quote = deal.active_quote
        if not quote:
            return Response(
                {'error': 'No active quote for this deal'},
                status=status.HTTP_404_NOT_FOUND
            )
        if not quote.pdf_file:
            # Auto-generate PDF if not yet generated
            from .services import QuoteLifecycleService
            try:
                quote = QuoteLifecycleService.generate_pdf(quote.pk)
            except Exception:
                return Response(
                    {'error': 'Failed to generate PDF'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        if not quote.pdf_file:
            return Response(
                {'error': 'PDF generation failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        from django.http import FileResponse
        return FileResponse(
            quote.pdf_file.open('rb'),
            content_type='application/pdf',
            as_attachment=True,
            filename=f'RailTech_Quote_{deal.id}.pdf'
        )


class QuoteViewSet(viewsets.ModelViewSet):
    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        queryset = Quote.objects.all().select_related('deal', 'status')
        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(deal__company_id__in=user_company_ids)

    @action(detail=True, methods=['post'], url_path='generate-pdf')
    def generate_pdf(self, request, pk=None):
        """Generate PDF for a quote."""
        quote = self.get_object()
        from .services import QuoteLifecycleService
        try:
            quote = QuoteLifecycleService.generate_pdf(quote.pk)
            return Response({
                'status': 'PDF generated',
                'pdf_url': request.build_absolute_uri(quote.pdf_file.url) if quote.pdf_file else None
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='send-to-client',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def send_to_client(self, request, pk=None):
        """Send quote to client (manager only). Freezes prices."""
        quote = self.get_object()
        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.send_to_client(quote.pk, request.user)
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """Client approves the quote."""
        quote = self.get_object()
        # Verify the user is the deal's client or company member
        user = request.user
        if not (user.is_superuser or user.is_manager_or_admin):
            if not user.memberships.filter(company=quote.deal.company, is_active=True).exists():
                return Response({'error': 'Only the client company can approve'}, status=status.HTTP_403_FORBIDDEN)

        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.approve_quote(quote.pk, request.user)
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Client rejects the quote."""
        quote = self.get_object()
        user = request.user
        if not (user.is_superuser or user.is_manager_or_admin):
            if not user.memberships.filter(company=quote.deal.company, is_active=True).exists():
                return Response({'error': 'Only the client company can reject'}, status=status.HTTP_403_FORBIDDEN)

        reason = request.data.get('reason', '')
        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.reject_quote(quote.pk, request.user, reason)
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='download-pdf')
    def download_pdf(self, request, pk=None):
        """Download the generated PDF."""
        quote = self.get_object()
        if not quote.pdf_file:
            return Response({'error': 'PDF not generated yet'}, status=status.HTTP_404_NOT_FOUND)

        from django.http import FileResponse
        return FileResponse(quote.pdf_file.open('rb'), content_type='application/pdf',
                            as_attachment=True, filename=quote.pdf_file.name.split('/')[-1])


class QuoteItemViewSet(viewsets.ModelViewSet):
    serializer_class = QuoteItemSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        queryset = QuoteItem.objects.all().select_related('product', 'quote')
        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(quote__deal__company_id__in=user_company_ids)


class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]
    filterset_fields = ['deal_id']

    def get_queryset(self):
        user = self.request.user
        queryset = Message.objects.all().order_by(
            'timestamp').select_related('sender', 'deal')
        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(deal__company_id__in=user_company_ids)

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)


class DashboardAnalyticsView(APIView):
    """
    Provides comprehensive dashboard analytics with KPIs for the main dashboard.
    GET /api/v1/crm/analytics/dashboard/?period=30d
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from catalog.models import Product
        from accounts.models import Company

        period = request.query_params.get('period', '30d')

        # Calculate period start date
        if period == '30d':
            period_start = timezone.now() - timedelta(days=30)
        elif period == '7d':
            period_start = timezone.now() - timedelta(days=7)
        elif period == '90d':
            period_start = timezone.now() - timedelta(days=90)
        else:
            period_start = timezone.now() - timedelta(days=30)

        # Get all deals and current period deals
        all_deals = Deal.objects.all()
        period_deals = Deal.objects.filter(created_at__gte=period_start)

        # Get previous period deals for comparison
        prev_period_start = period_start - (timezone.now() - period_start)
        prev_period_deals = Deal.objects.filter(
            created_at__gte=prev_period_start,
            created_at__lt=period_start
        )

        # Calculate deals volume
        current_volume = sum(d.total_value or Decimal('0') for d in period_deals)
        prev_volume = sum(d.total_value or Decimal('0') for d in prev_period_deals)
        volume_change = self._calculate_percentage_change(prev_volume, current_volume)

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
        published_products = Product.objects.filter(status__code='PUBLISHED').count()
        prev_published = Product.objects.filter(
            status__code='PUBLISHED',
            created_at__lt=period_start
        ).count()
        catalog_change = self._calculate_percentage_change(prev_published, published_products)

        # Clients count
        from accounts.models import CompanyType
        client_type = CompanyType.objects.filter(code='CLIENT').first()
        if client_type:
            current_clients = Company.objects.filter(types=client_type).distinct().count()
            # For previous period, use approximate (all clients - new ones)
            prev_clients = current_clients - Company.objects.filter(
                types=client_type,
                created_at__gte=period_start
            ).distinct().count()
        else:
            current_clients = 0
            prev_clients = 0
        clients_change = self._calculate_percentage_change(prev_clients, current_clients)

        # Deals by month (last 6 months)
        deals_by_month = self._get_deals_by_month(all_deals)

        # Activity by day (last 30 days)
        activity_by_day = self._get_activity_by_day()

        # Top products by deal frequency
        top_products = self._get_top_products()

        # Counterparties breakdown
        manufacturer_type = CompanyType.objects.filter(code='MANUFACTURER').first()
        supplier_type = CompanyType.objects.filter(code='SUPPLIER').first()

        counterparties = {
            'manufacturers': Company.objects.filter(types=manufacturer_type).count() if manufacturer_type else 0,
            'buyers': Company.objects.filter(types=client_type).count() if client_type else 0,
            'intermediaries': Company.objects.filter(types=supplier_type).count() if supplier_type else 0,
        }

        # Request completion percentage
        completed_quotes = Quote.objects.filter(
            status__code__in=['APPROVED', 'SENT']
        ).count()
        total_quotes = Quote.objects.count()
        completion_percentage = (completed_quotes / total_quotes * 100) if total_quotes > 0 else 0

        return Response({
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
        })

    def _calculate_percentage_change(self, previous, current):
        """Calculate percentage change between two values."""
        if previous == 0:
            return 0.0
        return round(((current - previous) / abs(previous)) * 100, 1)

    def _get_deals_by_month(self, deals):
        """Get deals aggregated by month for the last 6 months."""
        from django.db.models.functions import TruncMonth

        six_months_ago = timezone.now() - timedelta(days=180)
        monthly_deals = deals.filter(
            created_at__gte=six_months_ago
        ).extra(
            select={'month': 'DATE_TRUNC(\'month\', crm_deal.created_at)'}
        ).values('month').annotate(count=Count('id'), value=Sum('quotes__total_incl_vat'))

        result = []
        for item in monthly_deals:
            result.append({
                'month': item.get('month', ''),
                'count': item['count'],
                'value': float(item.get('value') or 0)
            })
        return result

    def _get_activity_by_day(self):
        """Get activity aggregated by day for the last 30 days."""
        from crm.models import ActivityLog

        thirty_days_ago = timezone.now() - timedelta(days=30)
        daily_activity = ActivityLog.objects.filter(
            timestamp__gte=thirty_days_ago
        ).extra(
            select={'day': 'DATE(crm_activitylog.timestamp)'}
        ).values('day').annotate(count=Count('id'))

        result = []
        for item in daily_activity:
            result.append({
                'day': item.get('day', ''),
                'count': item['count']
            })
        return result

    def _get_top_products(self, limit=5):
        """Get top products by deal frequency."""
        from catalog.models import Product

        top = Product.objects.annotate(
            deal_count=Count('quotes__items')
        ).order_by('-deal_count')[:limit]

        return [
            {
                'id': p.id,
                'name': p.name,
                'sku': p.sku,
                'deal_count': p.deal_count
            }
            for p in top
        ]


class CRMAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        from .services import get_crm_analytics_data
        data = get_crm_analytics_data()
        return Response(data)


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get_queryset(self):
        """Staff see all logs. Non-admin managers see only their own."""
        user = self.request.user
        queryset = ActivityLog.objects.all().select_related('user')
        if user.is_superuser:
            return queryset
        return queryset.filter(user=user)


class LeadSubmitThrottle(throttling.SimpleRateThrottle):
    scope = 'lead_submit'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class LeadCreateView(APIView):
    permission_classes = []
    throttle_classes = [LeadSubmitThrottle]

    def post(self, request):
        serializer = LeadSerializer(data=request.data)
        if serializer.is_valid():
            lead = serializer.save()
            ActivityLog.objects.create(
                action="Новый лид с сайта",
                detail=f"Получен запрос от {lead.name} ({lead.email}) через лендинг.",
                level='SUCCESS'
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
