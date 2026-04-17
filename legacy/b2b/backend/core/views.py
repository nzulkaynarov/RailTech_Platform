from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import serializers as drf_serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse

from core.models import SystemSetting
from core.permissions import IsManagerOrAdmin


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
            or getattr(request.user, 'is_manager_or_admin', False)
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
        is_staff = request.user.is_superuser or getattr(request.user, 'is_manager_or_admin', False)
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

        # --- Users (staff-only section — non-staff get zeros) ---
        if is_staff:
            users_total = CustomUser.objects.filter(is_active=True).count()
            users_admins = CustomUser.objects.filter(
                is_active=True, role__code='ADMIN'
            ).count()
            users_managers = CustomUser.objects.filter(
                is_active=True,
                role__code__in=['SALES_MANAGER', 'ACCOUNT_MANAGER'],
            ).count()
            users_employees = users_total - users_admins - users_managers
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
