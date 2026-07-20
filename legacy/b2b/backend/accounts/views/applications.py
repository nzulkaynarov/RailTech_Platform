from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import permissions
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts import services
from accounts.models import CompanyEntitlement, CompanyRoleApplication, SupplierSubscription
from accounts.serializers import (
    CompanyEntitlementSerializer,
    CompanyRoleApplicationSerializer,
    SupplierSubscriptionSerializer,
)
from core.permissions import OperatorScoped


@extend_schema_view(
    list=extend_schema(
        summary="List subscriptions",
        description="Returns all supplier subscriptions. Filterable by plan, status, company.",
        tags=["Accounts"],
    ),
    create=extend_schema(
        summary="Create subscription", description="Create a new supplier subscription.", tags=["Accounts"]
    ),
    retrieve=extend_schema(summary="Get subscription details", tags=["Accounts"]),
    update=extend_schema(summary="Update subscription", tags=["Accounts"]),
    partial_update=extend_schema(summary="Partially update subscription", tags=["Accounts"]),
    destroy=extend_schema(summary="Delete subscription", tags=["Accounts"]),
)
class SupplierSubscriptionViewSet(viewsets.ModelViewSet):
    """
    CRUD + status actions for supplier subscriptions.
    Admin/Manager only.
    """

    serializer_class = SupplierSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated, OperatorScoped]
    # Operator sub-capability per action (ADR-0004 G1). `mine`/`pay` are member-facing
    # (own IsAuthenticated permission_classes) so they bypass this map.
    operator_permissions = {
        "list": "billing.view",
        "retrieve": "billing.view",
        "export": "billing.view",
        "create": "billing.manage",
        "update": "billing.manage",
        "partial_update": "billing.manage",
        "destroy": "billing.manage",
        "activate": "billing.manage",
        "suspend": "billing.manage",
        "bulk_set_status": "billing.manage",
    }
    filterset_fields = ["plan", "status", "company"]
    search_fields = ["company__name", "company__inn"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return SupplierSubscription.objects.select_related("company", "currency").order_by("-created_at")

    @extend_schema(
        summary="My subscription",
        description=(
            "Returns the SupplierSubscription of the caller's primary company, "
            "if any. Available to any authenticated user with can_sell capability "
            "on a SUPPLIER/MANUFACTURER company. Platform admin viewers see 204."
        ),
        responses={
            200: SupplierSubscriptionSerializer,
            204: OpenApiResponse(description="No subscription for this user's company"),
            403: OpenApiResponse(description="Platform admin viewer cannot own a subscription"),
        },
        tags=["Accounts"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="mine",
        permission_classes=[permissions.IsAuthenticated],
    )
    def mine(self, request):
        """GET /api/v1/accounts/subscriptions/mine/ -- subscription of the current user's company."""
        user = request.user
        if getattr(user, "is_platform_admin", False):
            return Response(status=status.HTTP_403_FORBIDDEN)
        company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
        if not company_ids:
            return Response(status=status.HTTP_204_NO_CONTENT)
        sub = (
            SupplierSubscription.objects.select_related("company", "currency")
            .filter(company_id__in=company_ids)
            .order_by("-updated_at")
            .first()
        )
        if not sub:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(self.get_serializer(sub).data)

    @extend_schema(
        summary="Activate subscription",
        description="Set subscription status to ACTIVE.",
        responses={200: SupplierSubscriptionSerializer},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        """POST /api/v1/accounts/subscriptions/{id}/activate/"""
        sub = self.get_object()
        services.change_subscription_status(SupplierSubscription.objects.filter(pk=sub.pk), "ACTIVE")
        sub.refresh_from_db()
        return Response(self.get_serializer(sub).data)

    @extend_schema(
        summary="Suspend subscription",
        description="Set subscription status to SUSPENDED.",
        responses={200: SupplierSubscriptionSerializer},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        """POST /api/v1/accounts/subscriptions/{id}/suspend/"""
        sub = self.get_object()
        services.change_subscription_status(SupplierSubscription.objects.filter(pk=sub.pk), "SUSPENDED")
        sub.refresh_from_db()
        return Response(self.get_serializer(sub).data)

    @extend_schema(
        summary="Export subscriptions",
        description="Export filtered subscriptions as CSV or XLSX.",
        tags=["Accounts"],
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        from core.exporters import export_queryset

        qs = self.filter_queryset(self.get_queryset())
        return export_queryset(
            qs,
            request=request,
            filename="subscriptions",
            columns=[
                ("id", "ID", lambda s: s.id),
                ("company", "Company", lambda s: s.company.name if s.company_id else ""),
                ("inn", "INN", lambda s: s.company.inn if s.company_id else ""),
                ("plan", "Plan", lambda s: s.plan),
                ("status", "Status", lambda s: s.status),
                ("monthly_rate", "Monthly rate", lambda s: s.monthly_rate),
                ("currency", "Currency", lambda s: s.currency.code if s.currency_id else ""),
                ("valid_from", "Valid from", lambda s: s.valid_from.isoformat() if s.valid_from else ""),
                ("valid_until", "Valid until", lambda s: s.valid_until.isoformat() if s.valid_until else ""),
            ],
        )

    @extend_schema(
        summary="Bulk set subscription status",
        description="Platform Admin: apply a target status (ACTIVE | SUSPENDED) to multiple subscriptions.",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "integer"}},
                    "status": {"type": "string", "enum": ["ACTIVE", "SUSPENDED"]},
                    "reason": {"type": "string"},
                },
                "required": ["ids", "status"],
            }
        },
        responses={200: OpenApiResponse(description="affected count")},
        tags=["Accounts"],
    )
    @action(detail=False, methods=["post"], url_path="bulk-set-status")
    def bulk_set_status(self, request):
        ids = request.data.get("ids") or []
        target = (request.data.get("status") or "").upper()
        reason = (request.data.get("reason") or "").strip()
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "ids (non-empty list) is required"}, status=status.HTTP_400_BAD_REQUEST)
        if target not in ("ACTIVE", "SUSPENDED"):
            return Response({"detail": "status must be one of ACTIVE, SUSPENDED"}, status=status.HTTP_400_BAD_REQUEST)
        if target == "SUSPENDED" and not reason:
            return Response({"detail": "REASON_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        subs = SupplierSubscription.objects.filter(id__in=ids).select_related("company")
        affected_rows = services.change_subscription_status(subs, target)
        from core.audit import log_admin_action

        for sub in subs:
            log_admin_action(
                entity_type="subscription",
                entity_id=sub.id,
                action=f"Bulk: статус подписки → {target}",
                detail=f"{sub.company.name} · {target}" if sub.company_id else str(sub.id),
                actor=request.user,
                reason=reason,
                after={"status": target},
                level="WARNING" if target == "SUSPENDED" else "SUCCESS",
            )
        return Response({"affected": affected_rows, "target": target})

    @extend_schema(summary="Record subscription payment -- extends validity and activates", tags=["Accounts"])
    @action(detail=True, methods=["post"], url_path="pay", permission_classes=[permissions.IsAuthenticated])
    def pay(self, request, pk=None):
        sub = self.get_object()
        amount = request.data.get("amount", 0)
        months = int(request.data.get("months", 1))
        sub, error = services.record_subscription_payment(
            sub,
            amount,
            months=months,
            actor=request.user,
            manual=True,
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_403_FORBIDDEN)
        return Response(self.get_serializer(sub).data)


@extend_schema_view(
    list=extend_schema(
        summary="List role applications",
        description="Returns all company role applications. Filterable by status, type, company.",
        tags=["Accounts"],
    ),
    create=extend_schema(
        summary="Create role application", description="Submit a new role application for a company.", tags=["Accounts"]
    ),
    retrieve=extend_schema(summary="Get role application details", tags=["Accounts"]),
    update=extend_schema(summary="Update role application", tags=["Accounts"]),
    partial_update=extend_schema(summary="Partially update role application", tags=["Accounts"]),
    destroy=extend_schema(summary="Delete role application", tags=["Accounts"]),
)
class CompanyRoleApplicationViewSet(viewsets.ModelViewSet):
    """
    Company role applications:
      - Admin: full CRUD + approve/reject across all companies.
      - Company OWNER: may list/create/update only their own company's applications.
    """

    serializer_class = CompanyRoleApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    filterset_fields = ["status", "requested_type", "company"]
    search_fields = ["company__name", "company__inn"]
    ordering = ["-created_at"]

    _OWNER_ALLOWED_ACTIONS = {"list", "retrieve", "create", "partial_update", "update"}
    _ADMIN_ONLY_ACTIONS = {"approve", "reject", "destroy"}
    # Operator sub-capability for the moderation actions (ADR-0004 G1).
    operator_permissions = {
        "approve": "moderation.role_applications",
        "reject": "moderation.role_applications",
        "destroy": "moderation.role_applications",
    }

    def get_permissions(self):
        if self.action in self._ADMIN_ONLY_ACTIONS:
            return [permissions.IsAuthenticated(), OperatorScoped()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CompanyRoleApplication.objects.none()
        qs = CompanyRoleApplication.objects.select_related(
            "company", "requested_type", "submitted_by", "reviewed_by"
        ).order_by("-created_at")
        user = self.request.user
        if user.is_platform_admin:
            return qs
        own_company_ids = list(
            user.memberships.filter(
                is_active=True,
                role__code="OWNER",
            ).values_list("company_id", flat=True)
        )
        return qs.filter(company_id__in=own_company_ids)

    def perform_create(self, serializer):
        user = self.request.user
        company = serializer.validated_data.get("company")
        if not user.is_platform_admin:
            is_owner = user.memberships.filter(
                is_active=True,
                role__code="OWNER",
                company=company,
            ).exists()
            if not is_owner:
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("ONLY_COMPANY_OWNER_CAN_APPLY")
        serializer.save(submitted_by=user)

    def perform_update(self, serializer):
        user = self.request.user
        if not user.is_platform_admin:
            app = serializer.instance
            if app.status != "PENDING":
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied("APPLICATION_ALREADY_PROCESSED")
        serializer.save()

    @extend_schema(
        summary="Approve role application",
        description="Approve a pending role application. Adds the requested CompanyType to the company.",
        responses={200: CompanyRoleApplicationSerializer, 400: OpenApiResponse(description="Already processed")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/approve/"""
        app = self.get_object()
        result, error = services.approve_role_application(app, request.user)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)

    @extend_schema(
        summary="Reject role application",
        description="Reject a pending role application with an optional reason.",
        request=inline_serializer(
            "RejectRequest",
            fields={
                "reason": drf_serializers.CharField(required=False, default=""),
            },
        ),
        responses={200: CompanyRoleApplicationSerializer, 400: OpenApiResponse(description="Already processed")},
        tags=["Accounts"],
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        """POST /api/v1/accounts/role-applications/{id}/reject/"""
        app = self.get_object()
        reason = request.data.get("reason", "")
        result, error = services.reject_role_application(app, request.user, reason)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(result).data)


@extend_schema_view(
    list=extend_schema(summary="List company entitlements", tags=["Accounts"]),
    create=extend_schema(summary="Grant a company entitlement", tags=["Accounts"]),
    retrieve=extend_schema(summary="Get entitlement", tags=["Accounts"]),
    update=extend_schema(summary="Update entitlement", tags=["Accounts"]),
    partial_update=extend_schema(summary="Patch entitlement", tags=["Accounts"]),
    destroy=extend_schema(summary="Revoke (delete) entitlement", tags=["Accounts"]),
)
class CompanyEntitlementViewSet(viewsets.ModelViewSet):
    """Platform-admin CRUD of feature entitlements — the monetization control plane (ADR-0006 §3).

    Lets an operator grant a promo, put a company in DEMO, or DISABLE a feature; the app gates on
    `has_entitlement(company, FeatureKey)`. Gated by the billing operator capability (G1).
    """

    serializer_class = CompanyEntitlementSerializer
    permission_classes = [permissions.IsAuthenticated, OperatorScoped]
    operator_permissions = {
        "list": "billing.view",
        "retrieve": "billing.view",
        "choices": "billing.view",
        "create": "billing.manage",
        "update": "billing.manage",
        "partial_update": "billing.manage",
        "destroy": "billing.manage",
    }
    filterset_fields = ["company", "feature_key", "access"]
    search_fields = ["company__name", "company__inn", "feature_key"]
    ordering = ["-updated_at"]

    def get_queryset(self):
        return CompanyEntitlement.objects.select_related("company").order_by("-updated_at")

    @extend_schema(summary="Feature-key + access-state option lists for the entitlement form", tags=["Accounts"])
    @action(detail=False, methods=["get"], url_path="choices")
    def choices(self, request):
        """Backend-driven option lists for the admin form — the FE never hard-codes the FeatureKey
        or access enums; adding a feature key here surfaces it in the UI with no frontend change."""
        from accounts.constants import FeatureKey

        return Response(
            {
                "feature_keys": [{"value": value, "label": str(label)} for value, label in FeatureKey.choices],
                "access_states": [
                    {"value": value, "label": str(label)} for value, label in CompanyEntitlement.ACCESS_CHOICES
                ],
            }
        )
