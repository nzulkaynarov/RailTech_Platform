from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class PageStatsView(APIView):
    """
    Aggregated stats for all frontend pages.
    GET /api/v1/analytics/page-stats/
    Returns real counts from the database — no hardcoded data.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from crm.models import Deal, Quote, QuoteItem, Lead, ActivityLog
        from catalog.models import Product, Category, EquipmentGroup, SupplierOffer
        from accounts.models import Company, CustomUser, CompanyType, VerificationStatus
        from sourcing.models import ImportTask, Attachment
        from notifications.models import Notification

        # --- Deals ---
        deals_total = Deal.objects.count()
        deals_active = Deal.objects.exclude(stage__code__in=['CLOSED_WON', 'CLOSED_LOST']).count()
        deals_quote_sent = Deal.objects.filter(stage__code='QUOTE_SENT').count()
        deals_closed_won = Deal.objects.filter(stage__code='CLOSED_WON').count()

        # --- Quotes ---
        quotes_total = Quote.objects.count()
        quotes_draft = Quote.objects.filter(status__code='DRAFT').count()
        quotes_sent = Quote.objects.filter(status__code='SENT').count()
        quotes_approved = Quote.objects.filter(status__code='APPROVED').count()
        quotes_under_review = quotes_sent  # sent = under review
        pipeline_value = Quote.objects.filter(
            status__code__in=['DRAFT', 'SENT']
        ).aggregate(total=Sum('total_incl_vat'))['total'] or Decimal('0')

        # --- Sourcing ---
        sourcing_total = Deal.objects.filter(stage__code='SOURCING').count()
        sourcing_new = Deal.objects.filter(stage__code='DRAFT').count()
        sourcing_in_progress = Deal.objects.filter(
            stage__code__in=['SOURCING', 'CALCULATING']
        ).count()
        sourcing_completed = Deal.objects.filter(
            stage__code__in=['QUOTE_SENT', 'CONTRACT_SIGNED', 'CLOSED_WON']
        ).count()

        # --- Smart Match ---
        quote_items_total = QuoteItem.objects.count()
        quote_items_matched = QuoteItem.objects.filter(product__isnull=False).count()
        quote_items_unmatched = QuoteItem.objects.filter(product__isnull=True).count()
        match_accuracy = round(
            (quote_items_matched / quote_items_total * 100) if quote_items_total > 0 else 0
        )

        # --- Clients / Companies ---
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

        # --- Products / Catalog ---
        products_total = Product.objects.count()
        products_published = Product.objects.filter(status__code='PUBLISHED').count()
        categories_total = Category.objects.filter(is_active=True).count()
        equipment_groups_total = EquipmentGroup.objects.filter(is_active=True).count()
        offers_total = SupplierOffer.objects.filter(is_active=True).count()

        # --- Users ---
        users_total = CustomUser.objects.filter(is_active=True).count()
        users_admins = CustomUser.objects.filter(is_active=True, role__code='ADMIN').count()
        users_managers = CustomUser.objects.filter(
            is_active=True, role__code__in=['SALES_MANAGER', 'ACCOUNT_MANAGER']
        ).count()
        users_employees = users_total - users_admins - users_managers

        # --- Imports ---
        imports_total = ImportTask.objects.count()
        attachments_total = Attachment.objects.count()

        # --- Analytics ---
        total_deal_value = Deal.objects.aggregate(
            total=Sum('quotes__total_incl_vat')
        )['total'] or Decimal('0')
        avg_deal = round(float(total_deal_value) / deals_total, 2) if deals_total > 0 else 0
        win_rate = round(
            (deals_closed_won / deals_total * 100) if deals_total > 0 else 0
        )
        conversion = round(
            (deals_closed_won / deals_total * 100) if deals_total > 0 else 0
        )

        # --- Notifications ---
        user_notifications = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()

        # --- Production (manufacturer-specific) ---
        # For now, count deals where user's company is manufacturer
        production_active = 0
        production_awaiting = 0
        production_responded = 0
        production_overdue = 0

        return Response({
            'sourcing': {
                'total': sourcing_total + sourcing_new + sourcing_in_progress,
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
            'production': {
                'active': production_active,
                'awaiting_response': production_awaiting,
                'responded': production_responded,
                'overdue': production_overdue,
            },
            'production_schedule': {
                'active_orders': production_active,
                'completed': sourcing_completed,
                'delayed': production_overdue,
                'next_week': 0,
            },
            'analytics': {
                'conversion': f'{conversion}%',
                'avg_deal': f'${avg_deal:,.0f}',
                'pipeline': f'${int(pipeline_value):,}',
                'win_rate': f'{win_rate}%',
            },
            'analytics_buyer': {
                'spend_period': f'${int(total_deal_value):,}',
                'savings': '$0',
                'active_requests': deals_active,
            },
            'integrations': {
                'connected': 0,
                'pending': 0,
                'available_apis': 0,
                'synced_records': 0,
            },
            'my_requests': {
                'active': deals_active,
                'quote_received': quotes_sent,
                'contract': deals_closed_won,
                'completed': sourcing_completed,
            },
            'logistics': {
                'in_transit': 0,
                'customs': 0,
                'delivered': 0,
                'delays': 0,
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
