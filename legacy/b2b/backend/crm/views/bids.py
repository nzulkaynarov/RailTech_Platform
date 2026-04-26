from django.db.models import Q
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from crm import services as crm_services
from crm.models import SupplierBid
from crm.serializers import SupplierBidSerializer


class SupplierBidViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierBidSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head", "options"]
    filterset_fields = ["status", "supplier", "deal"]
    search_fields = ["deal__title", "deal__company__name", "supplier__name", "notes"]

    @extend_schema(
        summary="Export supplier bids",
        description="Admin/member-scoped CSV/XLSX export of supplier bids.",
        tags=["CRM"],
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        from core.exporters import export_queryset

        qs = self.filter_queryset(self.get_queryset())
        return export_queryset(
            qs,
            request=request,
            filename="supplier_bids",
            columns=[
                ("id", "ID", lambda b: b.id),
                ("deal", "Deal", lambda b: b.deal_id),
                ("deal_title", "Deal title", lambda b: b.deal.title if b.deal_id else ""),
                ("supplier", "Supplier", lambda b: b.supplier.name if b.supplier_id else ""),
                ("status", "Status", lambda b: b.status),
                ("total_amount", "Total", lambda b: b.total_amount),
                ("lead_time_days", "Lead days", lambda b: b.lead_time_days or ""),
                ("submitted_at", "Submitted", lambda b: b.submitted_at.isoformat() if b.submitted_at else ""),
                ("created_at", "Created", lambda b: b.created_at.isoformat() if b.created_at else ""),
            ],
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupplierBid.objects.none()
        user = self.request.user
        qs = (
            SupplierBid.objects.select_related("deal__company", "supplier", "currency")
            .prefetch_related(
                "items",
            )
            .order_by("-created_at")
        )
        if user.is_platform_admin:
            return qs
        # B2B visibility:
        #  * Supplier sees bids its company submitted.
        #  * Buyer (deal.company member) sees bids placed on their RFQs --
        #    required so the Buyer can pick a winner from the UI (CRIT-1).
        user_company_ids = list(
            user.memberships.filter(is_active=True).values_list("company_id", flat=True),
        )
        return qs.filter(
            Q(supplier_id__in=user_company_ids) | Q(deal__company_id__in=user_company_ids),
        ).distinct()

    @extend_schema(
        summary="Submit bid for an RFQ",
        tags=["CRM"],
        request=inline_serializer(
            "SubmitBid",
            fields={
                "deal_id": drf_serializers.IntegerField(),
                "supplier_id": drf_serializers.IntegerField(),
                "items": drf_serializers.ListField(child=drf_serializers.DictField()),
                "notes": drf_serializers.CharField(required=False, default=""),
                "lead_time_days": drf_serializers.IntegerField(required=False),
                "currency_id": drf_serializers.IntegerField(required=False),
            },
        ),
    )
    @action(detail=False, methods=["post"], url_path="submit")
    def submit(self, request):
        bid, err = crm_services.submit_supplier_bid(
            deal_id=int(request.data["deal_id"]),
            supplier_id=int(request.data["supplier_id"]),
            submitted_by=request.user,
            items=request.data.get("items", []),
            notes=request.data.get("notes", ""),
            lead_time_days=request.data.get("lead_time_days"),
            currency_id=request.data.get("currency_id"),
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(SupplierBidSerializer(bid).data, status=201)

    def _can_manage_bid(self, user, bid) -> bool:
        """Active member of the deal's buyer company (with can_buy) OR superuser.
        Platform-admin viewer is explicitly refused -- admins moderate, they don't
        accept business bids on behalf of the buyer.
        """
        from accounts.services import is_member_of, is_platform_admin_viewer

        if user.is_superuser:
            return True
        if is_platform_admin_viewer(user):
            return False
        return is_member_of(user, bid.deal.company_id, capability="buy")

    @extend_schema(summary="Accept bid", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request, pk=None):
        bid = self.get_object()
        if not self._can_manage_bid(request.user, bid):
            return Response({"detail": "NOT_AUTHORIZED_FOR_BID"}, status=403)
        bid, err = crm_services.accept_supplier_bid(int(pk), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(SupplierBidSerializer(bid).data)

    @extend_schema(summary="Reject bid", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        bid = self.get_object()
        if not self._can_manage_bid(request.user, bid):
            return Response({"detail": "NOT_AUTHORIZED_FOR_BID"}, status=403)
        bid, err = crm_services.reject_supplier_bid(int(pk), request.user, reason=request.data.get("reason", ""))
        if err:
            return Response({"detail": err}, status=400)
        return Response(SupplierBidSerializer(bid).data)
