from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, serializers as drf_serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse

from core import services
from core.models import SystemSetting, SupportTicket, SupportTicketMessage
from core.permissions import IsPlatformAdmin


# ──────────────────────────────────────────────────────────────────────────
# System Settings (singleton)
# ──────────────────────────────────────────────────────────────────────────


class SystemSettingSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = [
            'vat_rate', 'standard_margin', 'exchange_rate_usd_uzs',
            'platform_name', 'maintenance_mode',
            'is_two_factor_required', 'updated_at',
        ]
        read_only_fields = ['updated_at']


class SystemSettingsView(APIView):
    """
    GET  /api/v1/system-settings/ — read current settings (any authenticated user)
    PATCH /api/v1/system-settings/ — update settings (admin/manager only)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get system settings",
        description=(
            "Returns current platform settings: VAT rate, margin, exchange rate, etc. "
            "Any authenticated user can read."
        ),
        responses={200: SystemSettingSerializer},
        tags=['System'],
    )
    def get(self, request):
        settings_obj = SystemSetting.load()
        return Response(SystemSettingSerializer(settings_obj).data)

    @extend_schema(
        summary="Update system settings",
        description="Partially update platform settings. Admin/Manager only.",
        request=SystemSettingSerializer,
        responses={200: SystemSettingSerializer},
        tags=['System'],
    )
    def patch(self, request):
        # Write requires elevated permissions
        if not (
            request.user.is_superuser
            or request.user.is_platform_admin
        ):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()

        settings_obj = SystemSetting.load()
        serializer = SystemSettingSerializer(
            settings_obj, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(
    summary="Page stats for frontend",
    description=(
        "Aggregated statistics for all frontend pages. Returns real counts "
        "from the database for deals, quotes, sourcing, clients, products, "
        "users, imports, analytics, and more."
    ),
    responses={200: OpenApiResponse(description="Page stats object with nested sections")},
    tags=['Analytics'],
)
class PageStatsView(APIView):
    """
    Aggregated stats for all frontend pages.
    GET /api/v1/analytics/page-stats/
    Returns real counts from the database — no hardcoded data.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from crm.models import Deal, Quote, QuoteItem, Lead, ActivityLog
        from catalog.models import (
            Product, Category, EquipmentGroup, SupplierOffer,
        )
        from accounts.models import (
            Company, CustomUser, CompanyType, VerificationStatus,
        )
        from sourcing.models import ImportTask, Attachment
        from notifications.models import Notification

        # B2B data isolation: staff sees everything, regular users — only their companies
        is_staff = request.user.is_platform_admin
        if is_staff:
            deals_qs = Deal.objects.all()
            quotes_qs = Quote.objects.all()
            quote_items_qs = QuoteItem.objects.all()
        else:
            user_company_ids = request.user.memberships.filter(
                is_active=True
            ).values_list('company_id', flat=True)
            deals_qs = Deal.objects.filter(company_id__in=user_company_ids)
            quotes_qs = Quote.objects.filter(deal__company_id__in=user_company_ids)
            quote_items_qs = QuoteItem.objects.filter(quote__deal__company_id__in=user_company_ids)

        # --- Deals ---
        deals_total = deals_qs.count()
        deals_active = deals_qs.exclude(
            stage__code__in=['CLOSED_WON', 'CLOSED_LOST']
        ).count()
        deals_quote_sent = deals_qs.filter(
            stage__code='QUOTE_SENT'
        ).count()
        deals_closed_won = deals_qs.filter(
            stage__code='CLOSED_WON'
        ).count()

        # --- Quotes ---
        quotes_draft = quotes_qs.filter(status__code='DRAFT').count()
        quotes_sent = quotes_qs.filter(status__code='SENT').count()
        quotes_approved = quotes_qs.filter(
            status__code='APPROVED'
        ).count()
        quotes_under_review = quotes_sent  # sent = under review
        pipeline_value = quotes_qs.filter(
            status__code__in=['DRAFT', 'SENT']
        ).aggregate(total=Sum('total_incl_vat'))['total'] or Decimal('0')

        # --- Sourcing ---
        sourcing_total = deals_qs.filter(
            stage__code='SOURCING'
        ).count()
        sourcing_new = deals_qs.filter(stage__code='DRAFT').count()
        sourcing_in_progress = deals_qs.filter(
            stage__code__in=['SOURCING', 'CALCULATING']
        ).count()
        sourcing_completed = deals_qs.filter(
            stage__code__in=['QUOTE_SENT', 'CONTRACT_SIGNED', 'CLOSED_WON']
        ).count()

        # --- Smart Match ---
        quote_items_total = quote_items_qs.count()
        quote_items_matched = quote_items_qs.filter(
            product__isnull=False
        ).count()
        quote_items_unmatched = quote_items_qs.filter(
            product__isnull=True
        ).count()
        match_accuracy = round(
            (quote_items_matched / quote_items_total * 100)
            if quote_items_total > 0 else 0
        )

        # --- Clients / Companies (global — public catalog data) ---
        client_type = CompanyType.objects.filter(code='CLIENT').first()
        clients_total = Company.objects.count()
        clients_verified = Company.objects.filter(
            verification_status__code='L2_VERIFIED'
        ).count()
        clients_awaiting = Company.objects.filter(
            verification_status__code='PROFILE_SUBMITTED'
        ).count()
        clients_unverified = Company.objects.filter(
            verification_status__code='L1_UNVERIFIED'
        ).count()

        # --- Products / Catalog (global — public catalog data) ---
        products_total = Product.objects.count()
        products_published = Product.objects.filter(
            status__code='PUBLISHED'
        ).count()
        categories_total = Category.objects.filter(is_active=True).count()
        equipment_groups_total = EquipmentGroup.objects.filter(
            is_active=True
        ).count()
        offers_total = SupplierOffer.objects.filter(is_active=True).count()

        # --- Users (platform-admin-only section — others get zeros) ---
        if is_staff:
            users_total = CustomUser.objects.filter(is_active=True).count()
            users_admins = CustomUser.objects.filter(
                is_active=True, role__code='ADMIN'
            ).count()
            users_managers = 0  # platform-staff concept retired
            users_employees = users_total - users_admins
        else:
            users_total = users_admins = users_managers = users_employees = 0

        # --- Imports (staff-only) ---
        if is_staff:
            imports_total = ImportTask.objects.count()
            attachments_total = Attachment.objects.count()
        else:
            imports_total = attachments_total = 0

        # --- Analytics ---
        total_deal_value = deals_qs.aggregate(
            total=Sum('quotes__total_incl_vat')
        )['total'] or Decimal('0')
        avg_deal = (
            round(float(total_deal_value) / deals_total, 2)
            if deals_total > 0 else 0
        )
        win_rate = round(
            (deals_closed_won / deals_total * 100)
            if deals_total > 0 else 0
        )
        conversion = round(
            (deals_closed_won / deals_total * 100)
            if deals_total > 0 else 0
        )

        # --- Notifications ---
        user_notifications = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()

        return Response({
            'sourcing': {
                'total': sourcing_total + sourcing_in_progress,
                'new': sourcing_new,
                'in_progress': sourcing_in_progress,
                'completed': sourcing_completed,
            },
            'sourcing_match': {
                'unrecognized': quote_items_unmatched,
                'matches': quote_items_matched,
                'need_review': quote_items_unmatched,
                'accuracy': f'{match_accuracy}%',
            },
            'deals': {
                'total': deals_total,
                'active': deals_active,
                'quote_sent': deals_quote_sent,
                'closed_won': deals_closed_won,
            },
            'quotes': {
                'drafts': quotes_draft,
                'sent': quotes_sent,
                'approved': quotes_approved,
                'under_review': quotes_under_review,
                'total_amount': f'${int(pipeline_value):,}',
                'pipeline': f'${int(pipeline_value):,}',
            },
            'clients': {
                'total': clients_total,
                'verified': clients_verified,
                'awaiting_kyc': clients_awaiting,
                'unverified': clients_unverified,
            },
            'products': {
                'total': products_total,
                'published': products_published,
                'categories': categories_total,
                'equipment_groups': equipment_groups_total,
                'offers': offers_total,
            },
            'analytics': {
                'conversion': f'{conversion}%',
                'avg_deal': f'${avg_deal:,.0f}',
                'pipeline': f'${int(pipeline_value):,}',
                'win_rate': f'{win_rate}%',
            },
            'analytics_buyer': {
                'spend_period': f'${int(total_deal_value):,}',
                'active_requests': deals_active,
            },
            'my_requests': {
                'active': deals_active,
                'quote_received': quotes_sent,
                'contract': deals_closed_won,
                'completed': sourcing_completed,
            },
            'admin_users': {
                'total': users_total,
                'admins': users_admins,
                'managers': users_managers,
                'employees': users_employees,
            },
            'imports': {
                'total': imports_total,
                'attachments': attachments_total,
            },
            'notifications_unread': user_notifications,
        })


# ──────────────────────────────────────────────────────────────────────────
# Platform Admin dashboard — aggregate metrics for the PlatformAdminShell.
# ──────────────────────────────────────────────────────────────────────────

@extend_schema(
    summary="Platform admin dashboard metrics",
    description=(
        "Aggregate metrics for Platform Admin dashboard: users, companies, "
        "deals, subscriptions, pending attention counters, recent activity. "
        "Platform Admin only."
    ),
    responses={200: OpenApiResponse(description="Dashboard payload")},
    tags=['Analytics'],
)
class PlatformDashboardView(APIView):
    """GET /api/v1/analytics/platform-dashboard/"""
    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from datetime import timedelta
        from accounts.models import (
            Company, CustomUser, SupplierSubscription, CompanyRoleApplication,
        )
        from crm.models import Deal, Quote, ActivityLog, Invoice

        now = timezone.now()
        week_ago = now - timedelta(days=7)
        soon = now + timedelta(days=7)

        # Users
        users_qs = CustomUser.objects.all()
        users_total = users_qs.count()
        users_active = users_qs.filter(is_active=True).count()
        users_new_7d = users_qs.filter(date_joined__gte=week_ago).count()
        users_admins = users_qs.filter(role__code='ADMIN').count()

        # Companies
        companies_qs = Company.objects.all()
        companies_total = companies_qs.count()
        companies_by_type = {
            'BUYER': companies_qs.filter(types__code='CLIENT').distinct().count(),
            'SELLER': companies_qs.filter(types__code='SUPPLIER').distinct().count(),
            'MANUFACTURER': companies_qs.filter(types__code='MANUFACTURER').distinct().count(),
        }
        companies_pending_kyc = companies_qs.filter(
            verification_status__code__in=['L1_UNVERIFIED', 'PROFILE_SUBMITTED'],
        ).count()
        companies_verified = companies_qs.filter(
            verification_status__code__in=['L2_VERIFIED', 'L3_CONTRACTED'],
        ).count()

        # Deals
        deals_qs = Deal.objects.all()
        deals_total = deals_qs.count()
        deals_active = deals_qs.exclude(stage__code__in=['CLOSED_WON', 'CLOSED_LOST']).count()
        deals_won = deals_qs.filter(stage__code='CLOSED_WON').count()
        deals_lost = deals_qs.filter(stage__code='CLOSED_LOST').count()
        deals_by_stage = list(
            deals_qs.values('stage__code', 'stage__name')
            .annotate(count=Count('id'))
            .order_by('stage__sort_order')
        )

        # Revenue — approved quotes + closed-won
        pipeline_value = Quote.objects.filter(
            status__code__in=['SENT', 'APPROVED'],
        ).aggregate(total=Sum('total_incl_vat'))['total'] or Decimal('0')
        won_value = Quote.objects.filter(
            deal__stage__code='CLOSED_WON',
        ).aggregate(total=Sum('total_incl_vat'))['total'] or Decimal('0')

        # Subscriptions
        subs_qs = SupplierSubscription.objects.all()
        subs_active = subs_qs.filter(status='ACTIVE').count()
        subs_trial = subs_qs.filter(status='TRIAL').count()
        subs_past_due = subs_qs.filter(status='PAST_DUE').count()
        subs_suspended = subs_qs.filter(status='SUSPENDED').count()
        subs_expiring_7d = subs_qs.filter(
            status__in=['ACTIVE', 'TRIAL'],
            valid_until__isnull=False,
            valid_until__lte=soon.date(),
            valid_until__gte=now.date(),
        ).count()

        # Role applications
        role_apps_pending = CompanyRoleApplication.objects.filter(
            status__in=['PENDING', 'DOCUMENTS_REQUIRED', 'PAYMENT_REQUIRED'],
        ).count()

        # Overdue invoices — unpaid after due_date.
        overdue_invoices = Invoice.objects.filter(
            status__in=['ISSUED', 'PARTIAL', 'OVERDUE'],
            due_date__lt=now.date(),
        ).count()

        # Recent activity (last 20)
        recent_activity = [
            {
                'id': log.id,
                'action': log.action,
                'detail': log.detail,
                'level': log.level,
                'user_email': log.user.email if log.user else None,
                'timestamp': log.timestamp.isoformat(),
            }
            for log in ActivityLog.objects.select_related('user').order_by('-timestamp')[:20]
        ]

        # Pending attention counters — used for sidebar badges.
        attention = {
            'kyc': companies_pending_kyc,
            'role_applications': role_apps_pending,
            'subscriptions_past_due': subs_past_due,
            'subscriptions_expiring_7d': subs_expiring_7d,
            'overdue_invoices': overdue_invoices,
        }

        return Response({
            'users': {
                'total': users_total,
                'active': users_active,
                'new_7d': users_new_7d,
                'admins': users_admins,
            },
            'companies': {
                'total': companies_total,
                'by_type': companies_by_type,
                'pending_kyc': companies_pending_kyc,
                'verified': companies_verified,
            },
            'deals': {
                'total': deals_total,
                'active': deals_active,
                'won': deals_won,
                'lost': deals_lost,
                'by_stage': deals_by_stage,
                'pipeline_value': str(pipeline_value),
                'won_value': str(won_value),
            },
            'subscriptions': {
                'active': subs_active,
                'trial': subs_trial,
                'past_due': subs_past_due,
                'suspended': subs_suspended,
                'expiring_7d': subs_expiring_7d,
            },
            'attention': attention,
            'recent_activity': recent_activity,
        })


# ──────────────────────────────────────────────────────────────────────────
# Support tickets — прямой канал связи клиента с Platform Admin.
# ──────────────────────────────────────────────────────────────────────────


class SupportTicketMessageSerializer(drf_serializers.ModelSerializer):
    author_email = drf_serializers.CharField(source='author.email', read_only=True)
    author_full_name = drf_serializers.SerializerMethodField()
    author_is_admin = drf_serializers.SerializerMethodField()

    class Meta:
        model = SupportTicketMessage
        fields = [
            'id', 'ticket', 'text', 'is_internal',
            'author', 'author_email', 'author_full_name', 'author_is_admin',
            'created_at',
        ]
        read_only_fields = [
            'id', 'ticket', 'author', 'author_email', 'author_full_name',
            'author_is_admin', 'created_at',
        ]

    def get_author_full_name(self, obj: SupportTicketMessage) -> str:
        if not obj.author:
            return ''
        return obj.author.get_full_name() or obj.author.email

    def get_author_is_admin(self, obj: SupportTicketMessage) -> bool:
        return bool(obj.author and obj.author.is_platform_admin)


class SupportTicketSerializer(drf_serializers.ModelSerializer):
    created_by_email = drf_serializers.CharField(source='created_by.email', read_only=True)
    created_by_full_name = drf_serializers.SerializerMethodField()
    company_name = drf_serializers.CharField(source='company.name', read_only=True)
    assigned_to_email = drf_serializers.CharField(source='assigned_to.email', read_only=True)
    messages_count = drf_serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            'id', 'subject', 'description',
            'category', 'priority', 'status',
            'created_by', 'created_by_email', 'created_by_full_name',
            'company', 'company_name',
            'assigned_to', 'assigned_to_email',
            'messages_count',
            'created_at', 'updated_at', 'resolved_at',
        ]
        read_only_fields = [
            'id', 'created_by', 'created_by_email', 'created_by_full_name',
            'company', 'company_name', 'assigned_to', 'assigned_to_email',
            'messages_count', 'created_at', 'updated_at', 'resolved_at',
        ]

    def get_created_by_full_name(self, obj: SupportTicket) -> str:
        if not obj.created_by:
            return ''
        return obj.created_by.get_full_name() or obj.created_by.email

    def get_messages_count(self, obj: SupportTicket) -> int:
        return obj.messages.count()


@extend_schema_view(
    list=extend_schema(summary="List support tickets", tags=['Support']),
    retrieve=extend_schema(summary="Get support ticket", tags=['Support']),
    create=extend_schema(summary="Create support ticket", tags=['Support']),
    partial_update=extend_schema(summary="Update support ticket (admin)", tags=['Support']),
    destroy=extend_schema(summary="Delete support ticket (admin)", tags=['Support']),
)
class SupportTicketViewSet(viewsets.ModelViewSet):
    """
    Канал прямой связи: любой пользователь создаёт тикет, Platform Admin
    ведёт переписку и меняет статус.

    - пользователь: видит свои тикеты, может создавать и отвечать;
    - Platform Admin: видит все тикеты, меняет статус, назначает исполнителя,
      оставляет внутренние заметки (is_internal=True).
    """

    serializer_class = SupportTicketSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = {
        'status': ['exact', 'in'],
        'priority': ['exact', 'in'],
        'category': ['exact', 'in'],
        'assigned_to': ['exact'],
        'company': ['exact'],
    }
    search_fields = ['subject', 'description', 'created_by__email']
    ordering_fields = ['created_at', 'updated_at', 'priority', 'status']
    ordering = ['-created_at']
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return SupportTicket.objects.none()
        qs = SupportTicket.objects.select_related(
            'created_by', 'company', 'assigned_to',
        )
        user = self.request.user
        if user.is_platform_admin:
            return qs
        return qs.filter(created_by=user)

    def perform_create(self, serializer):
        data = serializer.validated_data
        ticket = services.create_support_ticket(
            author=self.request.user,
            subject=data['subject'],
            description=data['description'],
            category=data.get('category', SupportTicket.CATEGORY_QUESTION),
            priority=data.get('priority', SupportTicket.PRIORITY_NORMAL),
        )
        serializer.instance = ticket

    def perform_update(self, serializer):
        if not self.request.user.is_platform_admin:
            raise PermissionDenied('SUPPORT_ADMIN_ONLY')
        serializer.save()

    def perform_destroy(self, instance):
        if not self.request.user.is_platform_admin:
            raise PermissionDenied('SUPPORT_ADMIN_ONLY')
        instance.delete()

    @extend_schema(
        summary="List ticket messages",
        responses={200: SupportTicketMessageSerializer(many=True)},
        tags=['Support'],
    )
    @action(detail=True, methods=['get'], url_path='messages')
    def list_messages(self, request, pk=None):
        ticket = self.get_object()
        qs = ticket.messages.select_related('author').order_by('created_at')
        if not request.user.is_platform_admin:
            qs = qs.filter(is_internal=False)
        serializer = SupportTicketMessageSerializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Add ticket message",
        request=SupportTicketMessageSerializer,
        responses={201: SupportTicketMessageSerializer},
        tags=['Support'],
    )
    @action(detail=True, methods=['post'], url_path='add-message')
    def add_message(self, request, pk=None):
        ticket = self.get_object()
        text = (request.data.get('text') or '').strip()
        if not text:
            raise ValidationError({'text': 'SUPPORT_MESSAGE_TEXT_REQUIRED'})
        is_internal = bool(request.data.get('is_internal', False))
        if is_internal and not request.user.is_platform_admin:
            raise PermissionDenied('SUPPORT_INTERNAL_NOTE_ADMIN_ONLY')
        message = services.add_ticket_message(
            ticket=ticket, author=request.user, text=text, is_internal=is_internal,
        )
        return Response(
            SupportTicketMessageSerializer(message).data, status=201,
        )

    @extend_schema(
        summary="Change ticket status (admin)",
        responses={200: SupportTicketSerializer},
        tags=['Support'],
    )
    @action(detail=True, methods=['post'], url_path='change-status')
    def change_status(self, request, pk=None):
        if not request.user.is_platform_admin:
            raise PermissionDenied('SUPPORT_ADMIN_ONLY')
        ticket = self.get_object()
        status_code = request.data.get('status')
        updated = services.change_ticket_status(
            ticket=ticket, status=status_code, actor=request.user,
        )
        if updated is None:
            raise ValidationError({'status': 'SUPPORT_INVALID_STATUS'})
        return Response(SupportTicketSerializer(updated).data)

    @extend_schema(
        summary="Assign ticket to Platform Admin",
        responses={200: SupportTicketSerializer},
        tags=['Support'],
    )
    @action(detail=True, methods=['post'], url_path='assign')
    def assign(self, request, pk=None):
        if not request.user.is_platform_admin:
            raise PermissionDenied('SUPPORT_ADMIN_ONLY')
        ticket = self.get_object()
        from accounts.models import CustomUser
        assignee_id = request.data.get('assigned_to')
        if assignee_id is None:
            assignee = request.user
        else:
            try:
                assignee = CustomUser.objects.get(pk=assignee_id)
            except CustomUser.DoesNotExist:
                raise ValidationError({'assigned_to': 'SUPPORT_ASSIGNEE_NOT_FOUND'})
            if not assignee.is_platform_admin:
                raise ValidationError({'assigned_to': 'SUPPORT_ASSIGNEE_NOT_ADMIN'})
        updated = services.assign_ticket(ticket=ticket, assignee=assignee)
        return Response(SupportTicketSerializer(updated).data)
