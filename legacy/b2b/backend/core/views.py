from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import filters
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core import services
from core.models import SupportTicket, SupportTicketMessage, SystemSetting
from core.permissions import IsPlatformAdmin

# ──────────────────────────────────────────────────────────────────────────
# System Settings (singleton)
# ──────────────────────────────────────────────────────────────────────────


class SystemSettingSerializer(drf_serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = [
            "vat_rate",
            "standard_margin",
            "exchange_rate_usd_uzs",
            "platform_name",
            "maintenance_mode",
            "is_two_factor_required",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


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
        tags=["System"],
    )
    def get(self, request):
        settings_obj = SystemSetting.load()
        return Response(SystemSettingSerializer(settings_obj).data)

    @extend_schema(
        summary="Update system settings",
        description="Partially update platform settings. Admin/Manager only.",
        request=SystemSettingSerializer,
        responses={200: SystemSettingSerializer},
        tags=["System"],
    )
    def patch(self, request):
        # Write requires elevated permissions
        if not (request.user.is_superuser or request.user.is_platform_admin):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied()

        settings_obj = SystemSetting.load()
        serializer = SystemSettingSerializer(settings_obj, data=request.data, partial=True)
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
    tags=["Analytics"],
)
class PageStatsView(APIView):
    """
    Aggregated stats for all frontend pages.
    GET /api/v1/analytics/page-stats/
    Returns real counts from the database �� no hardcoded data.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.core.cache import cache

        from crm.models import Deal, Quote, QuoteItem
        from notifications.models import Notification

        cache_key = f"page_stats_{request.user.id}"
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        # B2B data isolation: staff sees everything, regular users — only their companies
        is_staff = request.user.is_platform_admin
        if is_staff:
            deals_qs = Deal.objects.all()
            quotes_qs = Quote.objects.all()
            quote_items_qs = QuoteItem.objects.all()
        else:
            user_company_ids = request.user.memberships.filter(is_active=True).values_list("company_id", flat=True)
            deals_qs = Deal.objects.filter(company_id__in=user_company_ids)
            quotes_qs = Quote.objects.filter(deal__company_id__in=user_company_ids)
            quote_items_qs = QuoteItem.objects.filter(quote__deal__company_id__in=user_company_ids)

        deal_stats = self._get_deal_stats(deals_qs)
        quote_stats = self._get_quote_stats(quotes_qs)
        sourcing_stats = self._get_sourcing_stats(deals_qs)
        match_stats = self._get_match_stats(quote_items_qs)
        client_stats = self._get_client_stats()
        catalog_stats = self._get_catalog_stats()
        user_stats = self._get_user_stats(is_staff)
        import_stats = self._get_import_stats(is_staff)
        analytics_stats = self._get_analytics_stats(deals_qs, deal_stats["total"], deal_stats["closed_won"])

        user_notifications = Notification.objects.filter(user=request.user, is_read=False).count()

        data = {
            "sourcing": {
                "total": sourcing_stats["total"] + sourcing_stats["in_progress"],
                "new": sourcing_stats["new"],
                "in_progress": sourcing_stats["in_progress"],
                "completed": sourcing_stats["completed"],
            },
            "sourcing_match": {
                "unrecognized": match_stats["unmatched"],
                "matches": match_stats["matched"],
                "need_review": match_stats["unmatched"],
                "accuracy": f'{match_stats["accuracy"]}%',
            },
            "deals": deal_stats,
            "quotes": {
                "drafts": quote_stats["drafts"],
                "sent": quote_stats["sent"],
                "approved": quote_stats["approved"],
                "under_review": quote_stats["sent"],
                "total_amount": f'${int(quote_stats["pipeline_value"]):,}',
                "pipeline": f'${int(quote_stats["pipeline_value"]):,}',
            },
            "clients": client_stats,
            "products": catalog_stats,
            "analytics": {
                "conversion": f'{analytics_stats["conversion"]}%',
                "avg_deal": f'${analytics_stats["avg_deal"]:,.0f}',
                "pipeline": f'${int(quote_stats["pipeline_value"]):,}',
                "win_rate": f'{analytics_stats["win_rate"]}%',
            },
            "analytics_buyer": {
                "spend_period": f'${int(analytics_stats["total_deal_value"]):,}',
                "active_requests": deal_stats["active"],
            },
            "my_requests": {
                "active": deal_stats["active"],
                "quote_received": quote_stats["sent"],
                "contract": deal_stats["closed_won"],
                "completed": sourcing_stats["completed"],
            },
            "admin_users": user_stats,
            "imports": import_stats,
            "notifications_unread": user_notifications,
        }
        cache.set(cache_key, data, timeout=30)
        return Response(data)

    @staticmethod
    def _get_deal_stats(deals_qs) -> dict:
        """Aggregate deal counts by stage — single query via aggregate()."""
        return deals_qs.aggregate(
            total=Count("id"),
            active=Count("id", filter=~Q(stage__code__in=["CLOSED_WON", "CLOSED_LOST"])),
            quote_sent=Count("id", filter=Q(stage__code="QUOTE_SENT")),
            closed_won=Count("id", filter=Q(stage__code="CLOSED_WON")),
        )

    @staticmethod
    def _get_quote_stats(quotes_qs) -> dict:
        """Aggregate quote counts and pipeline value — single query via aggregate()."""
        stats = quotes_qs.aggregate(
            drafts=Count("id", filter=Q(status__code="DRAFT")),
            sent=Count("id", filter=Q(status__code="SENT")),
            approved=Count("id", filter=Q(status__code="APPROVED")),
            pipeline_value=Sum(
                "total_incl_vat",
                filter=Q(status__code__in=["DRAFT", "SENT"]),
                default=Decimal("0"),
            ),
        )
        stats["pipeline_value"] = stats["pipeline_value"] or Decimal("0")
        return stats

    @staticmethod
    def _get_sourcing_stats(deals_qs) -> dict:
        """Aggregate sourcing-related deal counts — single query via aggregate()."""
        return deals_qs.aggregate(
            total=Count("id", filter=Q(stage__code="SOURCING")),
            new=Count("id", filter=Q(stage__code="DRAFT")),
            in_progress=Count("id", filter=Q(stage__code__in=["SOURCING", "CALCULATING"])),
            completed=Count("id", filter=Q(stage__code__in=["QUOTE_SENT", "CONTRACT_SIGNED", "CLOSED_WON"])),
        )

    @staticmethod
    def _get_match_stats(quote_items_qs) -> dict:
        """Aggregate Smart Match statistics — single query via aggregate()."""
        stats = quote_items_qs.aggregate(
            total=Count("id"),
            matched=Count("id", filter=Q(product__isnull=False)),
            unmatched=Count("id", filter=Q(product__isnull=True)),
        )
        total = stats["total"]
        stats["accuracy"] = round((stats["matched"] / total * 100) if total > 0 else 0)
        return stats

    @staticmethod
    def _get_client_stats() -> dict:
        """Aggregate company/client verification statistics — single query via aggregate()."""
        from accounts.models import Company

        return Company.objects.aggregate(
            total=Count("id"),
            verified=Count("id", filter=Q(verification_status__code="L2_VERIFIED")),
            awaiting_kyc=Count("id", filter=Q(verification_status__code="PROFILE_SUBMITTED")),
            unverified=Count("id", filter=Q(verification_status__code="L1_UNVERIFIED")),
        )

    @staticmethod
    def _get_catalog_stats() -> dict:
        """Aggregate product catalog statistics — 2 queries (products + rest)."""
        from catalog.models import Category, EquipmentGroup, Product, SupplierOffer

        product_stats = Product.objects.aggregate(
            total=Count("id"),
            published=Count("id", filter=Q(status__code="PUBLISHED")),
        )
        # Categories, equipment groups, and offers are separate tables — one aggregate each
        other_stats = {
            "categories": Category.objects.filter(is_active=True).count(),
            "equipment_groups": EquipmentGroup.objects.filter(is_active=True).count(),
            "offers": SupplierOffer.objects.filter(is_active=True).count(),
        }
        return {**product_stats, **other_stats}

    @staticmethod
    def _get_user_stats(is_staff: bool) -> dict:
        """Aggregate user statistics (platform-admin only; others get zeros) — single query."""
        if not is_staff:
            return {"total": 0, "admins": 0, "managers": 0, "employees": 0}
        from accounts.models import CustomUser

        stats = CustomUser.objects.filter(is_active=True).aggregate(
            total=Count("id"),
            admins=Count("id", filter=Q(role__code="ADMIN")),
        )
        stats["managers"] = 0
        stats["employees"] = stats["total"] - stats["admins"]
        return stats

    @staticmethod
    def _get_import_stats(is_staff: bool) -> dict:
        """Aggregate import statistics (staff-only). Already minimal queries (2 counts)."""
        if not is_staff:
            return {"total": 0, "attachments": 0}
        from sourcing.models import Attachment, ImportTask

        return {
            "total": ImportTask.objects.count(),
            "attachments": Attachment.objects.count(),
        }

    @staticmethod
    def _get_analytics_stats(deals_qs, deals_total: int, deals_closed_won: int) -> dict:
        """Aggregate analytics KPIs from deal data."""
        total_deal_value = deals_qs.aggregate(total=Sum("quotes__total_incl_vat"))["total"] or Decimal("0")
        avg_deal = round(float(total_deal_value) / deals_total, 2) if deals_total > 0 else 0
        win_rate = round((deals_closed_won / deals_total * 100) if deals_total > 0 else 0)
        return {
            "total_deal_value": total_deal_value,
            "avg_deal": avg_deal,
            "win_rate": win_rate,
            "conversion": win_rate,
        }


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
    tags=["Analytics"],
)
class PlatformDashboardView(APIView):
    """GET /api/v1/analytics/platform-dashboard/"""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]

    def get(self, request):
        from django.core.cache import cache

        cached = cache.get("platform_dashboard_v1")
        if cached:
            return Response(cached)

        from datetime import timedelta

        now = timezone.now()
        week_ago = now - timedelta(days=7)
        soon = now + timedelta(days=7)

        user_stats = self._get_user_stats(week_ago)
        company_stats = self._get_company_stats()
        deal_stats = self._get_deal_dashboard_stats()
        subscription_stats = self._get_subscription_stats(now, soon)
        attention = self._get_attention_counters(
            company_stats["pending_kyc"],
            subscription_stats,
            now,
        )

        data = {
            "users": user_stats,
            "companies": company_stats,
            "deals": deal_stats,
            "subscriptions": {
                "active": subscription_stats["active"],
                "trial": subscription_stats["trial"],
                "past_due": subscription_stats["past_due"],
                "suspended": subscription_stats["suspended"],
                "expiring_7d": subscription_stats["expiring_7d"],
            },
            "attention": attention,
            "recent_activity": self._get_recent_activity(),
        }
        cache.set("platform_dashboard_v1", data, timeout=60)
        return Response(data)

    @staticmethod
    def _get_user_stats(week_ago) -> dict:
        """Aggregate user counts for the platform dashboard — single query."""
        from accounts.models import CustomUser

        return CustomUser.objects.aggregate(
            total=Count("id"),
            active=Count("id", filter=Q(is_active=True)),
            new_7d=Count("id", filter=Q(date_joined__gte=week_ago)),
            admins=Count("id", filter=Q(role__code="ADMIN")),
        )

    @staticmethod
    def _get_company_stats() -> dict:
        """Aggregate company counts by type and KYC status — 2 queries."""
        from accounts.models import Company

        # Main aggregation (1 query) — counts by KYC status
        main_stats = Company.objects.aggregate(
            total=Count("id"),
            pending_kyc=Count("id", filter=Q(verification_status__code="PROFILE_SUBMITTED")),
            verified=Count("id", filter=Q(verification_status__code__in=["L2_VERIFIED", "L3_CONTRACTED"])),
        )
        # By-type breakdown via values().annotate() — 1 query for all types
        type_counts = dict(
            Company.objects.filter(
                types__code__in=["CLIENT", "SUPPLIER", "MANUFACTURER"],
            )
            .values_list("types__code")
            .annotate(count=Count("id", distinct=True))
            .values_list("types__code", "count")
        )
        return {
            "total": main_stats["total"],
            "by_type": {
                "BUYER": type_counts.get("CLIENT", 0),
                "SELLER": type_counts.get("SUPPLIER", 0),
                "MANUFACTURER": type_counts.get("MANUFACTURER", 0),
            },
            "pending_kyc": main_stats["pending_kyc"],
            "verified": main_stats["verified"],
        }

    @staticmethod
    def _get_deal_dashboard_stats() -> dict:
        """Aggregate deal counts and revenue for the platform dashboard — 3 queries."""
        from crm.models import Deal, Quote

        # 1 query: deal counts via aggregate
        deal_stats = Deal.objects.aggregate(
            total=Count("id"),
            active=Count("id", filter=~Q(stage__code__in=["CLOSED_WON", "CLOSED_LOST"])),
            won=Count("id", filter=Q(stage__code="CLOSED_WON")),
            lost=Count("id", filter=Q(stage__code="CLOSED_LOST")),
        )
        # 1 query: quote values via aggregate
        quote_values = Quote.objects.aggregate(
            pipeline_value=Sum("total_incl_vat", filter=Q(status__code__in=["SENT", "APPROVED"]), default=Decimal("0")),
            won_value=Sum("total_incl_vat", filter=Q(deal__stage__code="CLOSED_WON"), default=Decimal("0")),
        )
        # 1 query: by_stage breakdown
        by_stage = list(
            Deal.objects.values("stage__code", "stage__name").annotate(count=Count("id")).order_by("stage__sort_order")
        )
        return {
            **deal_stats,
            "by_stage": by_stage,
            "pipeline_value": str(quote_values["pipeline_value"] or Decimal("0")),
            "won_value": str(quote_values["won_value"] or Decimal("0")),
        }

    @staticmethod
    def _get_subscription_stats(now, soon) -> dict:
        """Aggregate subscription counts by status — single query via aggregate()."""
        from accounts.models import SupplierSubscription

        return SupplierSubscription.objects.aggregate(
            active=Count("id", filter=Q(status="ACTIVE")),
            trial=Count("id", filter=Q(status="TRIAL")),
            past_due=Count("id", filter=Q(status="PAST_DUE")),
            suspended=Count("id", filter=Q(status="SUSPENDED")),
            expiring_7d=Count(
                "id",
                filter=Q(
                    status__in=["ACTIVE", "TRIAL"],
                    valid_until__isnull=False,
                    valid_until__lte=soon.date(),
                    valid_until__gte=now.date(),
                ),
            ),
        )

    @staticmethod
    def _get_attention_counters(companies_pending_kyc: int, subscription_stats: dict, now) -> dict:
        """Compute pending-attention badge counters for the sidebar."""
        from accounts.models import CompanyRoleApplication
        from crm.models import Invoice

        role_apps_pending = CompanyRoleApplication.objects.filter(
            status__in=["PENDING", "DOCUMENTS_REQUIRED", "PAYMENT_REQUIRED"],
        ).count()
        overdue_invoices = Invoice.objects.filter(
            status__in=["ISSUED", "PARTIAL", "OVERDUE"],
            due_date__lt=now.date(),
        ).count()
        return {
            "kyc": companies_pending_kyc,
            "role_applications": role_apps_pending,
            "subscriptions_past_due": subscription_stats["past_due"],
            "subscriptions_expiring_7d": subscription_stats["expiring_7d"],
            "overdue_invoices": overdue_invoices,
        }

    @staticmethod
    def _get_recent_activity() -> list[dict]:
        """Fetch the last 20 activity log entries."""
        from crm.models import ActivityLog

        return [
            {
                "id": log.id,
                "action": log.action,
                "detail": log.detail,
                "level": log.level,
                "user_email": log.user.email if log.user else None,
                "timestamp": log.timestamp.isoformat(),
            }
            for log in ActivityLog.objects.select_related("user").order_by("-timestamp")[:20]
        ]


# ──────────────────────────────────────────────────────────────────────────
# Support tickets — прямой канал связи клиента с Platform Admin.
# ──────────────────────────────────────────────────────────────────────────


class SupportTicketMessageSerializer(drf_serializers.ModelSerializer):
    author_email = drf_serializers.CharField(source="author.email", read_only=True)
    author_full_name = drf_serializers.SerializerMethodField()
    author_is_admin = drf_serializers.SerializerMethodField()

    class Meta:
        model = SupportTicketMessage
        fields = [
            "id",
            "ticket",
            "text",
            "is_internal",
            "author",
            "author_email",
            "author_full_name",
            "author_is_admin",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "author",
            "author_email",
            "author_full_name",
            "author_is_admin",
            "created_at",
        ]

    def get_author_full_name(self, obj: SupportTicketMessage) -> str:
        if not obj.author:
            return ""
        return obj.author.get_full_name() or obj.author.email

    def get_author_is_admin(self, obj: SupportTicketMessage) -> bool:
        return bool(obj.author and obj.author.is_platform_admin)


class SupportTicketSerializer(drf_serializers.ModelSerializer):
    created_by_email = drf_serializers.CharField(source="created_by.email", read_only=True)
    created_by_full_name = drf_serializers.SerializerMethodField()
    company_name = drf_serializers.CharField(source="company.name", read_only=True)
    assigned_to_email = drf_serializers.CharField(source="assigned_to.email", read_only=True)
    messages_count = drf_serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "subject",
            "description",
            "category",
            "priority",
            "status",
            "created_by",
            "created_by_email",
            "created_by_full_name",
            "company",
            "company_name",
            "assigned_to",
            "assigned_to_email",
            "messages_count",
            "created_at",
            "updated_at",
            "resolved_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_email",
            "created_by_full_name",
            "company",
            "company_name",
            "assigned_to",
            "assigned_to_email",
            "messages_count",
            "created_at",
            "updated_at",
            "resolved_at",
        ]

    def get_created_by_full_name(self, obj: SupportTicket) -> str:
        if not obj.created_by:
            return ""
        return obj.created_by.get_full_name() or obj.created_by.email

    def get_messages_count(self, obj: SupportTicket) -> int:
        return getattr(obj, "messages_count_db", obj.messages.count())


@extend_schema_view(
    list=extend_schema(summary="List support tickets", tags=["Support"]),
    retrieve=extend_schema(summary="Get support ticket", tags=["Support"]),
    create=extend_schema(summary="Create support ticket", tags=["Support"]),
    partial_update=extend_schema(summary="Update support ticket (admin)", tags=["Support"]),
    destroy=extend_schema(summary="Delete support ticket (admin)", tags=["Support"]),
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
        "status": ["exact", "in"],
        "priority": ["exact", "in"],
        "category": ["exact", "in"],
        "assigned_to": ["exact"],
        "company": ["exact"],
    }
    search_fields = ["subject", "description", "created_by__email"]
    ordering_fields = ["created_at", "updated_at", "priority", "status"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupportTicket.objects.none()
        qs = SupportTicket.objects.select_related(
            "created_by",
            "company",
            "assigned_to",
        ).annotate(messages_count_db=Count("messages"))
        user = self.request.user
        if user.is_platform_admin:
            return qs
        return qs.filter(created_by=user)

    def perform_create(self, serializer):
        data = serializer.validated_data
        ticket = services.create_support_ticket(
            author=self.request.user,
            subject=data["subject"],
            description=data["description"],
            category=data.get("category", SupportTicket.CATEGORY_QUESTION),
            priority=data.get("priority", SupportTicket.PRIORITY_NORMAL),
        )
        serializer.instance = ticket

    def perform_update(self, serializer):
        if not self.request.user.is_platform_admin:
            raise PermissionDenied("SUPPORT_ADMIN_ONLY")
        serializer.save()

    def perform_destroy(self, instance):
        if not self.request.user.is_platform_admin:
            raise PermissionDenied("SUPPORT_ADMIN_ONLY")
        instance.delete()

    @extend_schema(
        summary="List ticket messages",
        responses={200: SupportTicketMessageSerializer(many=True)},
        tags=["Support"],
    )
    @action(detail=True, methods=["get"], url_path="messages")
    def list_messages(self, request, pk=None):
        ticket = self.get_object()
        qs = ticket.messages.select_related("author").order_by("created_at")
        if not request.user.is_platform_admin:
            qs = qs.filter(is_internal=False)
        serializer = SupportTicketMessageSerializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="Add ticket message",
        request=SupportTicketMessageSerializer,
        responses={201: SupportTicketMessageSerializer},
        tags=["Support"],
    )
    @action(detail=True, methods=["post"], url_path="add-message")
    def add_message(self, request, pk=None):
        ticket = self.get_object()
        text = (request.data.get("text") or "").strip()
        if not text:
            raise ValidationError({"text": "SUPPORT_MESSAGE_TEXT_REQUIRED"})
        is_internal = bool(request.data.get("is_internal", False))
        if is_internal and not request.user.is_platform_admin:
            raise PermissionDenied("SUPPORT_INTERNAL_NOTE_ADMIN_ONLY")
        message = services.add_ticket_message(
            ticket=ticket,
            author=request.user,
            text=text,
            is_internal=is_internal,
        )
        return Response(
            SupportTicketMessageSerializer(message).data,
            status=201,
        )

    @extend_schema(
        summary="Change ticket status (admin)",
        responses={200: SupportTicketSerializer},
        tags=["Support"],
    )
    @action(detail=True, methods=["post"], url_path="change-status")
    def change_status(self, request, pk=None):
        if not request.user.is_platform_admin:
            raise PermissionDenied("SUPPORT_ADMIN_ONLY")
        ticket = self.get_object()
        status_code = request.data.get("status")
        updated = services.change_ticket_status(
            ticket=ticket,
            status=status_code,
            actor=request.user,
        )
        if updated is None:
            raise ValidationError({"status": "SUPPORT_INVALID_STATUS"})
        return Response(SupportTicketSerializer(updated).data)

    @extend_schema(
        summary="Assign ticket to Platform Admin",
        responses={200: SupportTicketSerializer},
        tags=["Support"],
    )
    @action(detail=True, methods=["post"], url_path="assign")
    def assign(self, request, pk=None):
        if not request.user.is_platform_admin:
            raise PermissionDenied("SUPPORT_ADMIN_ONLY")
        ticket = self.get_object()
        from accounts.models import CustomUser

        assignee_id = request.data.get("assigned_to")
        if assignee_id is None:
            assignee = request.user
        else:
            try:
                assignee = CustomUser.objects.get(pk=assignee_id)
            except CustomUser.DoesNotExist:
                raise ValidationError({"assigned_to": "SUPPORT_ASSIGNEE_NOT_FOUND"})
            if not assignee.is_platform_admin:
                raise ValidationError({"assigned_to": "SUPPORT_ASSIGNEE_NOT_ADMIN"})
        updated = services.assign_ticket(ticket=ticket, assignee=assignee)
        return Response(SupportTicketSerializer(updated).data)
