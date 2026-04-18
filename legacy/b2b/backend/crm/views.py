from rest_framework import viewsets, status, throttling
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import (
    extend_schema, extend_schema_view, OpenApiResponse,
    OpenApiParameter, inline_serializer,
)
from rest_framework import serializers as drf_serializers
from .models import (
    Deal, DealStage, Quote, QuoteItem, QuoteStatus, Message, ActivityLog,
    Contract, Invoice, InvoiceItem, Payment, Act, Fulfillment,
    SupplierBid, SupplierBidItem, Lead,
)
from .serializers import (
    DealListSerializer, DealDetailSerializer, QuoteSerializer, QuoteItemSerializer,
    MessageSerializer, ActivityLogSerializer, LeadSerializer,
    ContractSerializer, InvoiceSerializer, InvoiceItemSerializer,
    PaymentSerializer, ActSerializer, FulfillmentSerializer,
    SupplierBidSerializer,
)
from rest_framework.permissions import IsAuthenticated
from core.permissions import IsManagerOrAdmin, IsOwnerOrManagerOrAdmin
from django.db.models import Count, Sum, Q, Subquery, OuterRef, Max, Prefetch
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from datetime import timedelta
from decimal import Decimal

from .services import transition_deal_stage, register_new_deal
from . import services as crm_services


@extend_schema_view(
    list=extend_schema(
        summary="List deals",
        description=(
            "Returns deals accessible to the current user. "
            "Admins/managers see all; clients see only their company's deals."
        ),
        tags=['CRM'],
    ),
    create=extend_schema(
        summary="Create deal",
        description=(
            "Create a new deal. The client is auto-assigned to the current user, "
            "and the company is set from the user's primary company."
        ),
        tags=['CRM'],
    ),
    retrieve=extend_schema(
        summary="Get deal details",
        description="Returns full deal details including all quotes and their items.",
        tags=['CRM'],
    ),
    update=extend_schema(summary="Update deal", tags=['CRM']),
    partial_update=extend_schema(summary="Partially update deal", tags=['CRM']),
    destroy=extend_schema(summary="Delete deal", tags=['CRM']),
)
class DealViewSet(viewsets.ModelViewSet):
    """
    CRUD for deals (the core CRM entity).

    Deal lifecycle: DRAFT → KYC_PENDING → SOURCING → CALCULATING →
    QUOTE_SENT → CONTRACT_SIGNED → CLOSED_WON / CLOSED_LOST.
    """
    def get_serializer_class(self):
        if self.action == 'list':
            return DealListSerializer
        return DealDetailSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Deal.objects.none()
        user = self.request.user
        quote_items_qs = QuoteItem.objects.select_related(
            'product', 'product__domain_type', 'offer', 'offer__supplier', 'frozen_currency'
        )
        quotes_qs = Quote.objects.select_related('status').prefetch_related(
            Prefetch('items', queryset=quote_items_qs)
        ).order_by('-version')
        queryset = Deal.objects.all().select_related(
            'client', 'manager', 'company', 'stage'
        ).prefetch_related(Prefetch('quotes', queryset=quotes_qs))

        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(company_id__in=user_company_ids)

    def perform_create(self, serializer):
        primary_company = self.request.user.primary_company
        if not primary_company:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                "company": _("User has no associated company. Please complete your company profile."),
            })
        save_kwargs = dict(client=self.request.user, company=primary_company)
        if not serializer.validated_data.get('stage'):
            draft_stage = DealStage.objects.filter(code='DRAFT').first()
            if draft_stage:
                save_kwargs['stage'] = draft_stage
        deal = serializer.save(**save_kwargs)
        register_new_deal(deal, self.request.user)

    @extend_schema(
        summary="Change deal stage",
        description=(
            "Transition the deal to a new stage using FSM validation. "
            "Valid transitions are enforced by the backend."
        ),
        request=inline_serializer('ChangeStageRequest', fields={
            'stage_code': drf_serializers.CharField(
                help_text="Target stage code (e.g. SOURCING, CALCULATING, QUOTE_SENT)"
            ),
        }),
        responses={
            200: DealDetailSerializer,
            400: OpenApiResponse(description="stage_code is required"),
            422: OpenApiResponse(description="Invalid stage transition"),
        },
        tags=['CRM'],
    )
    @action(detail=True, methods=['post'], url_path='change-stage')
    def change_stage(self, request, pk=None):
        """Change deal stage with FSM validation."""
        deal = self.get_object()
        stage_code = request.data.get('stage_code')
        if not stage_code:
            return Response(
                {'detail': 'STAGE_CODE_REQUIRED'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deal, error = transition_deal_stage(deal, stage_code, actor=request.user)
        if error:
            return Response(
                {'detail': error},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        serializer = DealDetailSerializer(deal)
        return Response(serializer.data)

    @extend_schema(
        summary="Force change deal stage (admin)",
        description=(
            "Transition the deal to ANY stage, bypassing FSM validation. "
            "Admin/Manager only. Use for emergency fixes."
        ),
        request=inline_serializer('ForceChangeStageRequest', fields={
            'stage_code': drf_serializers.CharField(),
            'reason': drf_serializers.CharField(required=False, default=''),
        }),
        responses={
            200: DealDetailSerializer,
            400: OpenApiResponse(description="stage_code is required"),
            404: OpenApiResponse(description="Stage not found"),
        },
        tags=['CRM'],
    )
    @action(
        detail=True, methods=['post'], url_path='force-change-stage',
        permission_classes=[IsAuthenticated, IsManagerOrAdmin],
    )
    def force_change_stage(self, request, pk=None):
        deal = self.get_object()
        stage_code = request.data.get('stage_code')
        reason = request.data.get('reason', '')
        if not stage_code:
            return Response({'detail': 'STAGE_CODE_REQUIRED'},
                            status=status.HTTP_400_BAD_REQUEST)
        deal, error = transition_deal_stage(
            deal, stage_code, actor=request.user, reason=reason, validate_fsm=False,
        )
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DealDetailSerializer(deal).data)

    @extend_schema(
        summary="Export deal PDF",
        description=(
            "Export PDF of the deal's active quote. "
            "Auto-generates the PDF if not yet created."
        ),
        responses={
            (200, 'application/pdf'): OpenApiResponse(description="PDF file download"),
            404: OpenApiResponse(description="No active quote"),
            500: OpenApiResponse(description="PDF generation failed"),
        },
        tags=['CRM'],
    )
    @extend_schema(summary="Open RFQ — move deal to RFQ_OPEN and notify suppliers", tags=['CRM'],
                   request=inline_serializer('OpenRFQ', fields={
                       'supplier_ids': drf_serializers.ListField(child=drf_serializers.IntegerField(), required=False),
                   }))
    @action(detail=True, methods=['post'], url_path='open-rfq',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def open_rfq(self, request, pk=None):
        deal, err = crm_services.open_rfq(
            int(pk), request.user,
            supplier_ids=request.data.get('supplier_ids') or None,
        )
        if err:
            return Response({'detail': err}, status=400)
        return Response(DealDetailSerializer(deal).data)

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


@extend_schema_view(
    list=extend_schema(
        summary="List quotes",
        description="Returns quotes accessible to the current user with items.",
        tags=['CRM'],
    ),
    create=extend_schema(summary="Create quote", tags=['CRM']),
    retrieve=extend_schema(
        summary="Get quote details",
        description="Returns full quote details including all line items.",
        tags=['CRM'],
    ),
    update=extend_schema(summary="Update quote", tags=['CRM']),
    partial_update=extend_schema(summary="Partially update quote", tags=['CRM']),
    destroy=extend_schema(summary="Delete quote", tags=['CRM']),
)
class QuoteViewSet(viewsets.ModelViewSet):
    """
    CRUD for quotes (commercial proposals).

    Quote lifecycle: DRAFT → SENT → APPROVED / REJECTED.
    Includes PDF generation, send-to-client, approve, and reject actions.
    """
    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Quote.objects.none()
        user = self.request.user
        queryset = Quote.objects.all().select_related(
            'deal', 'deal__company', 'deal__stage', 'status'
        ).prefetch_related(
            'items', 'items__product', 'items__product__domain_type',
            'items__offer', 'items__offer__supplier', 'items__frozen_currency'
        )
        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(deal__company_id__in=user_company_ids)

    def perform_create(self, serializer):
        """Auto-increment version for new quotes within a deal."""
        deal = serializer.validated_data.get('deal')
        if deal:
            max_version = deal.quotes.aggregate(max_v=Max('version'))['max_v'] or 0
            serializer.save(version=max_version + 1)
        else:
            serializer.save()

    @extend_schema(
        summary="Generate quote PDF",
        description="Generate a PDF file for the quote using WeasyPrint.",
        responses={
            200: OpenApiResponse(description="PDF generated, URL returned"),
            500: OpenApiResponse(description="PDF generation failed"),
        },
        tags=['CRM'],
    )
    @action(detail=True, methods=['post'], url_path='generate-pdf')
    def generate_pdf(self, request, pk=None):
        """Generate PDF for a quote."""
        quote = self.get_object()
        from .services import QuoteLifecycleService
        try:
            quote = QuoteLifecycleService.generate_pdf(quote.pk)
            return Response({
                'status': 'PDF generated',
                'url': (
                    request.build_absolute_uri(quote.pdf_file.url)
                    if quote.pdf_file else None
                ),
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        summary="Send quote to client",
        description=(
            "Send the quote to the client. Freezes prices at current values. "
            "Manager/Admin only."
        ),
        responses={200: QuoteSerializer},
        tags=['CRM'],
    )
    @action(detail=True, methods=['post'], url_path='send-to-client',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def send_to_client(self, request, pk=None):
        """Send quote to client (manager only). Freezes prices."""
        quote = self.get_object()
        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.send_to_client(quote.pk, request.user)
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @extend_schema(
        summary="Approve quote",
        description="Client approves the quote. Only the client's company members or staff can approve.",
        responses={
            200: QuoteSerializer,
            403: OpenApiResponse(description="Not authorized"),
        },
        tags=['CRM'],
    )
    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """Client approves the quote."""
        quote = self.get_object()
        # Verify the user is the deal's client or company member
        user = request.user
        if not (user.is_superuser or user.is_manager_or_admin):
            if not user.memberships.filter(
                company=quote.deal.company, is_active=True
            ).exists():
                return Response(
                    {'error': 'Only the client company can approve'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.approve_quote(quote.pk, request.user)
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @extend_schema(
        summary="Reject quote",
        description="Client rejects the quote with an optional reason.",
        request=inline_serializer('RejectQuoteRequest', fields={
            'reason': drf_serializers.CharField(required=False, default=''),
        }),
        responses={
            200: QuoteSerializer,
            403: OpenApiResponse(description="Not authorized"),
        },
        tags=['CRM'],
    )
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Client rejects the quote."""
        quote = self.get_object()
        user = request.user
        if not (user.is_superuser or user.is_manager_or_admin):
            if not user.memberships.filter(
                company=quote.deal.company, is_active=True
            ).exists():
                return Response(
                    {'error': 'Only the client company can reject'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        reason = request.data.get('reason', '')
        from .services import QuoteLifecycleService
        quote = QuoteLifecycleService.reject_quote(
            quote.pk, request.user, reason
        )
        serializer = self.get_serializer(quote)
        return Response(serializer.data)

    @extend_schema(
        summary="Download quote PDF",
        description="Download the previously generated PDF file for a quote.",
        responses={
            (200, 'application/pdf'): OpenApiResponse(description="PDF file"),
            404: OpenApiResponse(description="PDF not generated yet"),
        },
        tags=['CRM'],
    )
    @action(detail=True, methods=['get'], url_path='download-pdf')
    def download_pdf(self, request, pk=None):
        """Download the generated PDF."""
        quote = self.get_object()
        if not quote.pdf_file:
            return Response(
                {'error': 'PDF not generated yet'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.http import FileResponse
        return FileResponse(
            quote.pdf_file.open('rb'),
            content_type='application/pdf',
            as_attachment=True,
            filename=quote.pdf_file.name.split('/')[-1],
        )


@extend_schema_view(
    list=extend_schema(
        summary="List quote items",
        description="Returns quote line items accessible to the current user.",
        tags=['CRM'],
    ),
    create=extend_schema(
        summary="Create quote item",
        description="Add a line item to a quote.",
        tags=['CRM'],
    ),
    retrieve=extend_schema(summary="Get quote item", tags=['CRM']),
    update=extend_schema(summary="Update quote item", tags=['CRM']),
    partial_update=extend_schema(summary="Partially update quote item", tags=['CRM']),
    destroy=extend_schema(summary="Delete quote item", tags=['CRM']),
)
class QuoteItemViewSet(viewsets.ModelViewSet):
    """CRUD for quote line items (products, quantities, pricing)."""
    serializer_class = QuoteItemSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]
    filterset_fields = {
        'quote__deal_id': ['exact'],
        'product': ['isnull', 'exact'],
    }

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return QuoteItem.objects.none()
        user = self.request.user
        queryset = QuoteItem.objects.all().select_related(
            'product', 'product__domain_type', 'quote',
            'offer', 'offer__supplier', 'frozen_currency'
        )
        if user.is_superuser or user.is_manager_or_admin:
            return queryset

        user_company_ids = user.memberships.filter(
            is_active=True).values_list('company_id', flat=True)
        return queryset.filter(quote__deal__company_id__in=user_company_ids)

    @extend_schema(summary="Manually reassign product for a quote item", tags=['CRM'],
                   request=inline_serializer('ReassignProduct', fields={
                       'product_id': drf_serializers.IntegerField(allow_null=True),
                   }))
    @action(detail=True, methods=['post'], url_path='reassign-product',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def reassign_product(self, request, pk=None):
        product_id = request.data.get('product_id')
        item, err = crm_services.reassign_quote_item_product(
            int(pk), request.user, product_id=int(product_id) if product_id else None,
        )
        if err:
            return Response({'detail': err}, status=400)
        return Response(QuoteItemSerializer(item).data)

    @extend_schema(summary="Get top-N smart-match candidates for this item", tags=['CRM'])
    @action(detail=True, methods=['get'], url_path='match-candidates',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def match_candidates(self, request, pk=None):
        from sourcing.services import smart_match_candidates
        item = self.get_object()
        raw = item.imported_raw_name or (item.product.name if item.product else '')
        domain_hint = item.product.domain_type.code if (item.product and item.product.domain_type) else None
        candidates = smart_match_candidates(raw, limit=5, domain_hint=domain_hint)
        return Response({'raw': raw, 'candidates': candidates})


@extend_schema_view(
    list=extend_schema(
        summary="List messages",
        description="Returns deal messages. Filterable by deal_id.",
        tags=['CRM'],
    ),
    create=extend_schema(
        summary="Send message",
        description="Send a message in a deal chat. Sender is auto-assigned.",
        tags=['CRM'],
    ),
    retrieve=extend_schema(summary="Get message", tags=['CRM']),
    update=extend_schema(summary="Update message", tags=['CRM']),
    partial_update=extend_schema(summary="Partially update message", tags=['CRM']),
    destroy=extend_schema(summary="Delete message", tags=['CRM']),
)
class MessageViewSet(viewsets.ModelViewSet):
    """
    CRUD for deal messages (chat within a deal).

    Messages are ordered by timestamp. The sender is auto-assigned
    to the current user on creation.
    """
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]
    filterset_fields = ['deal_id']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Message.objects.none()
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
        is_staff = request.user.is_superuser or getattr(request.user, 'is_manager_or_admin', False)
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

        # Get deals — scoped to user's companies for non-staff
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

        # Activity by day (last 30 days) — scoped to user's companies
        activity_by_day = self._get_activity_by_day(user_company_ids)

        # Top products by deal frequency — scoped to user's companies
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
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        from .services import get_crm_analytics_data
        data = get_crm_analytics_data()
        return Response(data)


@extend_schema_view(
    list=extend_schema(
        summary="List activity logs",
        description=(
            "Returns activity logs. Superusers see all; "
            "managers see only their own logs."
        ),
        tags=['CRM'],
    ),
    retrieve=extend_schema(summary="Get activity log entry", tags=['CRM']),
)
class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to activity logs for audit trail."""
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


@extend_schema(
    summary="Submit lead",
    description=(
        "Submit a lead from the landing page. "
        "No authentication required. Rate-limited."
    ),
    request=LeadSerializer,
    responses={
        201: LeadSerializer,
        400: OpenApiResponse(description="Validation error"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    },
    tags=['CRM'],
)
class LeadCreateView(APIView):
    """Public endpoint for lead submission from the landing page."""
    permission_classes = []
    throttle_classes = [LeadSubmitThrottle]

    def post(self, request):
        serializer = LeadSerializer(data=request.data)
        if serializer.is_valid():
            lead = serializer.save()
            ActivityLog.objects.create(
                action="Новый лид с сайта",
                detail=(
                    f"Получен запрос от {lead.name} ({lead.email}) "
                    f"через лендинг."
                ),
                level='SUCCESS'
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(summary="List deal stages", tags=['CRM']),
)
class DealStageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DealStage.objects.all().order_by('sort_order', 'name')
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{'code': s.code, 'name': s.name} for s in self.get_queryset()]
        return Response(data)


@extend_schema_view(
    list=extend_schema(summary="List quote statuses", tags=['CRM']),
)
class QuoteStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = QuoteStatus.objects.all().order_by('sort_order', 'name')
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{'code': s.code, 'name': s.name} for s in self.get_queryset()]
        return Response(data)


class Phase2StatusChoicesView(APIView):
    """Expose TextChoices-style status sets of the Phase 2 business models
    so the frontend doesn't hardcode them (IRON RULE 2).
    GET /api/v1/crm/status-choices/
    Response: {contract: [{code, label}], invoice: [...], ...}
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        def to_list(choices):
            return [{'code': c[0], 'label': str(c[1])} for c in choices]

        return Response({
            'contract': to_list(Contract.STATUS_CHOICES),
            'invoice': to_list(Invoice.STATUS_CHOICES),
            'act': to_list(Act.STATUS_CHOICES),
            'fulfillment': to_list(Fulfillment.STATUS_CHOICES),
            'supplier_bid': to_list(SupplierBid.STATUS_CHOICES),
            'payment_method': to_list(Payment.METHOD_CHOICES),
        })


# ──────────────────────────────────────────────────────────────────────────
# Contracts / Invoices / Payments / Acts / Fulfillment / SupplierBids / Leads
# ──────────────────────────────────────────────────────────────────────────


class LeadViewSet(viewsets.ModelViewSet):
    """Manager/admin CRUD for leads + convert-to-deal."""
    serializer_class = LeadSerializer
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]
    queryset = Lead.objects.all().order_by('-created_at')

    @extend_schema(summary="Convert lead to deal", tags=['CRM'],
                   request=inline_serializer('ConvertLead', fields={
                       'company_id': drf_serializers.IntegerField(required=False),
                   }))
    @action(detail=True, methods=['post'], url_path='convert')
    def convert(self, request, pk=None):
        from accounts.models import Company
        lead = self.get_object()
        company = None
        if request.data.get('company_id'):
            company = Company.objects.filter(pk=request.data['company_id']).first()
        deal, err = crm_services.convert_lead_to_deal(lead, request.user, company=company)
        if err:
            return Response({'detail': err}, status=400)
        return Response({'deal_id': deal.id, 'stage': deal.stage.code if deal.stage else None}, status=201)


class ContractViewSet(viewsets.ModelViewSet):
    """Contracts — generated from approved quotes, double-signed."""
    serializer_class = ContractSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Contract.objects.none()
        u = self.request.user
        qs = Contract.objects.select_related('deal__company', 'quote', 'currency',
                                             'client_signer', 'manager_signer').order_by('-created_at')
        if u.is_superuser or getattr(u, 'is_manager_or_admin', False):
            return qs
        user_company_ids = u.memberships.filter(is_active=True).values_list('company_id', flat=True)
        return qs.filter(deal__company_id__in=user_company_ids)

    @extend_schema(summary="Generate contract from a quote", tags=['CRM'],
                   request=inline_serializer('GenContract', fields={
                       'quote_id': drf_serializers.IntegerField(),
                       'notes': drf_serializers.CharField(required=False, default=''),
                   }))
    @action(detail=False, methods=['post'], url_path='generate-from-quote',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def generate_from_quote(self, request):
        quote_id = request.data.get('quote_id')
        if not quote_id:
            return Response({'detail': 'QUOTE_ID_REQUIRED'}, status=400)
        contract, err = crm_services.generate_contract_from_quote(
            int(quote_id), actor=request.user, notes=request.data.get('notes', ''),
        )
        if err:
            return Response({'detail': err}, status=400)
        return Response(ContractSerializer(contract).data, status=201)

    @extend_schema(summary="Sign contract by client", tags=['CRM'])
    @action(detail=True, methods=['post'], url_path='sign-client')
    def sign_client(self, request, pk=None):
        contract, err = crm_services.sign_contract_by_client(int(pk), request.user)
        if err:
            return Response({'detail': err}, status=400)
        return Response(ContractSerializer(contract).data)

    @extend_schema(summary="Sign contract by manager (RailTech side)", tags=['CRM'])
    @action(detail=True, methods=['post'], url_path='sign-manager',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def sign_manager(self, request, pk=None):
        contract, err = crm_services.sign_contract_by_manager(int(pk), request.user)
        if err:
            return Response({'detail': err}, status=400)
        return Response(ContractSerializer(contract).data)

    @extend_schema(summary="Upload signed copy", tags=['CRM'])
    @action(detail=True, methods=['post'], url_path='upload-signed',
            parser_classes=[__import__('rest_framework').parsers.MultiPartParser,
                            __import__('rest_framework').parsers.FormParser])
    def upload_signed(self, request, pk=None):
        contract = self.get_object()
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'detail': 'NO_FILE_PROVIDED'}, status=400)
        contract.signed_file = file_obj
        contract.save(update_fields=['signed_file', 'updated_at'])
        return Response(ContractSerializer(contract).data)

    @extend_schema(summary="Cancel contract", tags=['CRM'])
    @action(detail=True, methods=['post'], url_path='cancel',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def cancel(self, request, pk=None):
        contract, err = crm_services.cancel_contract(int(pk), request.user, reason=request.data.get('reason', ''))
        if err:
            return Response({'detail': err}, status=400)
        return Response(ContractSerializer(contract).data)


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Invoice.objects.none()
        u = self.request.user
        qs = Invoice.objects.select_related('deal__company', 'contract', 'currency').prefetch_related(
            'items', 'payments',
        ).order_by('-created_at')
        if u.is_superuser or getattr(u, 'is_manager_or_admin', False):
            return qs
        user_company_ids = u.memberships.filter(is_active=True).values_list('company_id', flat=True)
        return qs.filter(deal__company_id__in=user_company_ids)

    @extend_schema(summary="Generate invoice from a signed contract", tags=['CRM'])
    @action(detail=False, methods=['post'], url_path='generate-from-contract',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def generate_from_contract(self, request):
        contract_id = request.data.get('contract_id')
        due_days = int(request.data.get('due_days', 14))
        if not contract_id:
            return Response({'detail': 'CONTRACT_ID_REQUIRED'}, status=400)
        invoice, err = crm_services.generate_invoice_from_contract(
            int(contract_id), actor=request.user, due_days=due_days,
        )
        if err:
            return Response({'detail': err}, status=400)
        return Response(InvoiceSerializer(invoice).data, status=201)

    @extend_schema(summary="Record a payment against this invoice", tags=['CRM'],
                   request=inline_serializer('RecordPayment', fields={
                       'amount': drf_serializers.DecimalField(max_digits=14, decimal_places=2),
                       'paid_at': drf_serializers.DateField(),
                       'method': drf_serializers.CharField(required=False, default='BANK_TRANSFER'),
                       'reference': drf_serializers.CharField(required=False, default=''),
                   }))
    @action(detail=True, methods=['post'], url_path='record-payment',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def record_payment(self, request, pk=None):
        payment, err = crm_services.record_payment(
            int(pk), actor=request.user,
            amount=request.data.get('amount'),
            paid_at=request.data.get('paid_at'),
            method=request.data.get('method', 'BANK_TRANSFER'),
            reference=request.data.get('reference', ''),
            proof_file=request.FILES.get('proof_file'),
        )
        if err:
            return Response({'detail': err}, status=400)
        return Response(PaymentSerializer(payment).data, status=201)

    @extend_schema(summary="Generate Act for this invoice", tags=['CRM'])
    @action(detail=True, methods=['post'], url_path='generate-act',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def generate_act(self, request, pk=None):
        act, err = crm_services.generate_act(int(pk), actor=request.user)
        if err:
            return Response({'detail': err}, status=400)
        return Response(ActSerializer(act).data, status=201)


class PaymentViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Payment.objects.none()
        u = self.request.user
        qs = Payment.objects.select_related('invoice__deal__company').order_by('-paid_at')
        if u.is_superuser or getattr(u, 'is_manager_or_admin', False):
            return qs
        user_company_ids = u.memberships.filter(is_active=True).values_list('company_id', flat=True)
        return qs.filter(invoice__deal__company_id__in=user_company_ids)


class ActViewSet(viewsets.ModelViewSet):
    serializer_class = ActSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Act.objects.none()
        u = self.request.user
        qs = Act.objects.select_related('deal__company', 'contract', 'invoice').order_by('-created_at')
        if u.is_superuser or getattr(u, 'is_manager_or_admin', False):
            return qs
        user_company_ids = u.memberships.filter(is_active=True).values_list('company_id', flat=True)
        return qs.filter(deal__company_id__in=user_company_ids)

    @extend_schema(summary="Sign act (mark as SIGNED)", tags=['CRM'])
    @action(detail=True, methods=['post'], url_path='sign',
            parser_classes=[__import__('rest_framework').parsers.MultiPartParser,
                            __import__('rest_framework').parsers.FormParser])
    def sign(self, request, pk=None):
        act, err = crm_services.sign_act(int(pk), request.user, signed_file=request.FILES.get('signed_file'))
        if err:
            return Response({'detail': err}, status=400)
        return Response(ActSerializer(act).data)


class FulfillmentViewSet(viewsets.ModelViewSet):
    serializer_class = FulfillmentSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrManagerOrAdmin]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Fulfillment.objects.none()
        u = self.request.user
        qs = Fulfillment.objects.select_related('deal__company').order_by('-updated_at')
        if u.is_superuser or getattr(u, 'is_manager_or_admin', False):
            return qs
        user_company_ids = u.memberships.filter(is_active=True).values_list('company_id', flat=True)
        return qs.filter(deal__company_id__in=user_company_ids)

    @extend_schema(summary="Update fulfillment status", tags=['CRM'])
    @action(detail=False, methods=['post'], url_path='update-status',
            permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def update_status(self, request):
        deal_id = request.data.get('deal_id')
        status_code = request.data.get('status')
        if not deal_id or not status_code:
            return Response({'detail': 'DEAL_ID_AND_STATUS_REQUIRED'}, status=400)
        extra = {k: request.data.get(k) for k in ('tracking_number', 'carrier',
                                                  'expected_delivery_date', 'notes')}
        obj, err = crm_services.update_fulfillment_status(
            int(deal_id), request.user, status_code, **extra,
        )
        if err:
            return Response({'detail': err}, status=400)
        return Response(FulfillmentSerializer(obj).data)


class SupplierBidViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierBidSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return SupplierBid.objects.none()
        u = self.request.user
        qs = SupplierBid.objects.select_related('deal__company', 'supplier', 'currency').prefetch_related(
            'items',
        ).order_by('-created_at')
        if u.is_superuser or getattr(u, 'is_manager_or_admin', False):
            return qs
        # B2B visibility:
        #  * Supplier sees bids its company submitted.
        #  * Buyer (deal.company member) sees bids placed on their RFQs —
        #    required so the Buyer can pick a winner from the UI (CRIT-1).
        user_company_ids = list(
            u.memberships.filter(is_active=True).values_list('company_id', flat=True),
        )
        return qs.filter(
            Q(supplier_id__in=user_company_ids)
            | Q(deal__company_id__in=user_company_ids),
        ).distinct()

    @extend_schema(summary="Submit bid for an RFQ", tags=['CRM'],
                   request=inline_serializer('SubmitBid', fields={
                       'deal_id': drf_serializers.IntegerField(),
                       'supplier_id': drf_serializers.IntegerField(),
                       'items': drf_serializers.ListField(child=drf_serializers.DictField()),
                       'notes': drf_serializers.CharField(required=False, default=''),
                       'lead_time_days': drf_serializers.IntegerField(required=False),
                       'currency_id': drf_serializers.IntegerField(required=False),
                   }))
    @action(detail=False, methods=['post'], url_path='submit')
    def submit(self, request):
        bid, err = crm_services.submit_supplier_bid(
            deal_id=int(request.data['deal_id']),
            supplier_id=int(request.data['supplier_id']),
            submitted_by=request.user,
            items=request.data.get('items', []),
            notes=request.data.get('notes', ''),
            lead_time_days=request.data.get('lead_time_days'),
            currency_id=request.data.get('currency_id'),
        )
        if err:
            return Response({'detail': err}, status=400)
        return Response(SupplierBidSerializer(bid).data, status=201)

    def _can_manage_bid(self, user, bid) -> bool:
        """Active member of the deal's buyer company (with can_buy) OR superuser.
        Platform-admin viewer is explicitly refused — admins moderate, they don't
        accept business bids on behalf of the buyer.
        """
        from accounts.services import is_member_of, is_platform_admin_viewer
        if user.is_superuser:
            return True
        if is_platform_admin_viewer(user):
            return False
        return is_member_of(user, bid.deal.company_id, capability='buy')

    @extend_schema(summary="Accept bid", tags=['CRM'])
    @action(detail=True, methods=['post'], url_path='accept')
    def accept(self, request, pk=None):
        bid = self.get_object()
        if not self._can_manage_bid(request.user, bid):
            return Response({'detail': 'NOT_AUTHORIZED_FOR_BID'}, status=403)
        bid, err = crm_services.accept_supplier_bid(int(pk), request.user)
        if err:
            return Response({'detail': err}, status=400)
        return Response(SupplierBidSerializer(bid).data)

    @extend_schema(summary="Reject bid", tags=['CRM'])
    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        bid = self.get_object()
        if not self._can_manage_bid(request.user, bid):
            return Response({'detail': 'NOT_AUTHORIZED_FOR_BID'}, status=403)
        bid, err = crm_services.reject_supplier_bid(int(pk), request.user, reason=request.data.get('reason', ''))
        if err:
            return Response({'detail': err}, status=400)
        return Response(SupplierBidSerializer(bid).data)
