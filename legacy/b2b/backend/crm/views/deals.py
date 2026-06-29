from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsCompanyMemberOrPlatformAdmin, OperatorScoped
from crm.constants import DealStageCode
from crm.models import Deal, DealStage, Quote, QuoteItem
from crm.serializers import DealDetailSerializer, DealListSerializer, QuoteItemSerializer
from crm.services import (
    buyer_add_request_item,
    buyer_add_request_items,
    buyer_update_request_meta,
    force_transition_deal_stage,
    register_new_deal,
    route_request_to_sellers,
    submit_request,
    transition_deal_stage,
)


@extend_schema_view(
    list=extend_schema(
        summary="List deals",
        description=(
            "Returns deals accessible to the current user. "
            "Admins/managers see all; clients see only their company's deals."
        ),
        tags=["CRM"],
    ),
    create=extend_schema(
        summary="Create deal",
        description=(
            "Create a new deal. The client is auto-assigned to the current user, "
            "and the company is set from the user's primary company."
        ),
        tags=["CRM"],
    ),
    retrieve=extend_schema(
        summary="Get deal details",
        description="Returns full deal details including all quotes and their items.",
        tags=["CRM"],
    ),
    update=extend_schema(summary="Update deal", tags=["CRM"]),
    partial_update=extend_schema(summary="Partially update deal", tags=["CRM"]),
    destroy=extend_schema(summary="Delete deal", tags=["CRM"]),
)
class DealViewSet(viewsets.ModelViewSet):
    """
    CRUD for deals (the core CRM entity).

    Deal lifecycle: DRAFT -> KYC_PENDING -> SOURCING -> CALCULATING ->
    QUOTE_SENT -> CONTRACT_SIGNED -> CLOSED_WON / CLOSED_LOST.
    """

    def get_serializer_class(self):
        if self.action == "list":
            return DealListSerializer
        return DealDetailSerializer

    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    # Operator sub-capability for the force-override action (ADR-0004 G1).
    operator_permissions = {"force_change_stage": "moderation.force_override"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Deal.objects.none()
        user = self.request.user
        quote_items_qs = QuoteItem.objects.select_related(
            "product", "product__domain_type", "offer", "offer__supplier", "frozen_currency"
        )
        quotes_qs = (
            Quote.objects.select_related("status")
            .prefetch_related(Prefetch("items", queryset=quote_items_qs))
            .order_by("-version")
        )
        queryset = (
            Deal.objects.all()
            .select_related("client", "manager", "company", "stage")
            .prefetch_related(Prefetch("quotes", queryset=quotes_qs), "target_sellers")
        )

        from accounts.services.permissions import seller_visible_deal_ids

        # Platform admin sees every deal (oversight). A seller acting in a seller
        # context is scoped to the RFQs ROUTED to them (multi-seller confidentiality
        # keystone — replaces the old see-all leak where seller A saw seller B's
        # buyers' заявки). A dual seller+buyer user in the BUYER context (or a pure
        # buyer) falls through to its own-company scope.
        if getattr(user, "is_platform_admin", False):
            return queryset

        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            return queryset.filter(id__in=visible_deal_ids)

        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return queryset.filter(company_id__in=user_company_ids)

    def destroy(self, request, *args, **kwargs):
        """Members may delete only their own DRAFT deals; once a deal enters the
        workflow (RFQ_OPEN and beyond) it carries bids/quotes/contracts and must
        not be silently dropped — only a platform admin can remove it then
        (checkup 2026-06-10: destroy was open to any member at any stage)."""
        deal = self.get_object()
        if not request.user.is_platform_admin:
            stage_code = deal.stage.code if deal.stage_id else None
            if stage_code and stage_code != DealStageCode.DRAFT:
                return Response(
                    {"detail": "DEAL_DELETE_ONLY_DRAFT"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        from rest_framework.exceptions import PermissionDenied, ValidationError

        user = self.request.user
        contact_id = self.request.data.get("contact_id")

        if contact_id:
            # Seller opens a deal for an OFFLINE client from their own book (client base).
            # company = the client's company, client = None, contact = the offline contact.
            from accounts.models import Contact
            from accounts.services.clients import seller_clients

            contact = Contact.objects.select_related("company").filter(pk=contact_id).first()
            if contact is None:
                raise ValidationError({"contact_id": _("Contact not found.")})
            # Ownership: the contact's company must be in THIS seller's book (no cross-tenant).
            if not seller_clients(user).filter(pk=contact.company_id).exists():
                raise PermissionDenied("CONTACT_NOT_IN_YOUR_BOOK")
            save_kwargs = dict(company=contact.company, contact=contact, client=None)
        else:
            # Buyer-initiated deal: scoped to the user's own company.
            primary_company = user.primary_company
            if not primary_company:
                raise ValidationError(
                    {"company": _("User has no associated company. Please complete your company profile.")}
                )
            # Capability guard (server-side, not UI-only): opening a buyer RFQ is a
            # buy-side action — a member without can_buy (e.g. a seller-only member of
            # this company) must be refused here, not merely hidden in the cart UI.
            from accounts.services.permissions import is_member_of, is_platform_admin_viewer

            if is_platform_admin_viewer(user):
                raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
            if not is_member_of(user, primary_company.id, capability="buy"):
                raise PermissionDenied("ONLY_BUYER_CAN_CREATE_REQUEST")
            save_kwargs = dict(client=user, company=primary_company)

        if not serializer.validated_data.get("stage"):
            draft_stage = DealStage.objects.filter(code=DealStageCode.DRAFT).first()
            if draft_stage:
                save_kwargs["stage"] = draft_stage
        deal = serializer.save(**save_kwargs)
        register_new_deal(deal, self.request.user)

    @extend_schema(
        summary="Change deal stage",
        description=(
            "Transition the deal to a new stage using FSM validation. " "Valid transitions are enforced by the backend."
        ),
        request=inline_serializer(
            "ChangeStageRequest",
            fields={
                "stage_code": drf_serializers.CharField(
                    help_text="Target stage code (e.g. SOURCING, CALCULATING, QUOTE_SENT)"
                ),
            },
        ),
        responses={
            200: DealDetailSerializer,
            400: OpenApiResponse(description="stage_code is required"),
            422: OpenApiResponse(description="Invalid stage transition"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="change-stage")
    def change_stage(self, request, pk=None):
        """Change deal stage with FSM validation."""
        deal = self.get_object()
        stage_code = request.data.get("stage_code")
        if not stage_code:
            return Response(
                {"detail": "STAGE_CODE_REQUIRED"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        deal, error = transition_deal_stage(deal, stage_code, actor=request.user)
        if error:
            return Response(
                {"detail": error},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        serializer = DealDetailSerializer(deal)
        return Response(serializer.data)

    @extend_schema(
        summary="Add a line item to the buyer's request",
        description=(
            "Buyer-only. Appends a row (name + quantity) to the deal's request. "
            "Creates the underlying DRAFT quote on first add. Allowed only while "
            "the seller has not taken the deal into work."
        ),
        request=inline_serializer(
            "AddRequestItemRequest",
            fields={
                "name": drf_serializers.CharField(),
                "quantity": drf_serializers.IntegerField(required=False, default=1),
            },
        ),
        responses={201: QuoteItemSerializer},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="add-request-item")
    def add_request_item(self, request, pk=None):
        """Buyer appends one item to their request (заявка)."""
        deal = self.get_object()
        item = buyer_add_request_item(
            request.user,
            deal,
            name=request.data.get("name", ""),
            quantity=request.data.get("quantity", 1),
            unit=request.data.get("unit", ""),
            unit_code=request.data.get("unit_code", ""),
            note=request.data.get("note", ""),
            mpn=request.data.get("mpn", ""),
        )
        return Response(
            QuoteItemSerializer(item, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Bulk-add request line items (catalog cart)",
        description="Buyer-only. Adds many lines at once; catalog items link by product_id.",
        request=inline_serializer(
            "AddRequestItemsRequest",
            fields={"items": drf_serializers.ListField(child=drf_serializers.DictField())},
        ),
        responses={201: QuoteItemSerializer(many=True)},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="add-request-items")
    def add_request_items(self, request, pk=None):
        """Buyer adds a batch of request lines (the catalog cart checkout)."""
        deal = self.get_object()
        items = buyer_add_request_items(request.user, deal, request.data.get("items", []))
        return Response(
            QuoteItemSerializer(items, many=True, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Submit the buyer's request (RFQ) to the seller",
        description=(
            "Buyer-only. Issues the request to the seller: Draft → RFQ_OPEN. "
            "Requires ≥1 line and no incomplete lines. After this the request locks."
        ),
        responses={200: DealDetailSerializer},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="submit-request")
    def submit_request(self, request, pk=None):
        """Buyer issues the RFQ (the «Отправить заявку» step)."""
        deal = submit_request(request.user, self.get_object())
        return Response(DealDetailSerializer(deal, context={"request": request}).data)

    @extend_schema(
        summary="Edit the request header (title + note to seller)",
        description="Buyer-only, while the request is still DRAFT.",
        request=inline_serializer(
            "UpdateRequestMeta",
            fields={
                "title": drf_serializers.CharField(required=False),
                "notes": drf_serializers.CharField(required=False, allow_blank=True),
            },
        ),
        responses={200: DealDetailSerializer},
        tags=["CRM"],
    )
    @action(detail=True, methods=["patch"], url_path="update-request-meta")
    def update_request_meta(self, request, pk=None):
        """Buyer edits the request title / note-to-seller while drafting."""
        deal = buyer_update_request_meta(
            request.user,
            self.get_object(),
            title=request.data.get("title"),
            notes=request.data.get("notes"),
        )
        return Response(DealDetailSerializer(deal, context={"request": request}).data)

    @extend_schema(
        summary="Route the request (RFQ) to seller companies",
        description=(
            "Buyer-only, while the deal is still DRAFT. Addresses a (typically "
            "free-text) заявка to chosen seller companies — multi-seller routing. "
            "Idempotent; each id must be an active SUPPLIER-type company."
        ),
        request=inline_serializer(
            "RouteRequestRequest",
            fields={
                "seller_company_ids": drf_serializers.ListField(child=drf_serializers.IntegerField()),
            },
        ),
        responses={200: DealDetailSerializer},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="route")
    def route(self, request, pk=None):
        """Buyer routes the request to the chosen seller company/companies."""
        route_request_to_sellers(
            request.user,
            self.get_object(),
            request.data.get("seller_company_ids", []),
        )
        # Re-fetch so target_sellers_data reflects the freshly-created routing rows
        # (the get_object() instance carries a stale prefetched M2M cache).
        deal = self.get_queryset().get(pk=pk)
        return Response(DealDetailSerializer(deal, context={"request": request}).data)

    @extend_schema(
        summary="List seller companies for the routing picker",
        description="Buyer-facing lightweight directory of active SUPPLIER companies.",
        responses={
            200: inline_serializer(
                "SupplierPickerItem",
                fields={
                    "id": drf_serializers.IntegerField(),
                    "name": drf_serializers.CharField(),
                },
                many=True,
            )
        },
        tags=["CRM"],
    )
    @action(detail=False, methods=["get"], url_path="suppliers", pagination_class=None)
    def suppliers(self, request):
        """Active SUPPLIER companies for the buyer's routing picker."""
        from accounts.constants import SELLER_COMPANY_TYPES
        from accounts.models import Company

        sellers = (
            Company.objects.filter(types__code__in=SELLER_COMPANY_TYPES)
            .distinct()
            .order_by("name")
            .values("id", "name")
        )
        return Response(list(sellers))

    @extend_schema(
        summary="Force change deal stage (admin)",
        description=(
            "Transition the deal to ANY stage, bypassing FSM validation. "
            "Admin/Manager only. Use for emergency fixes."
        ),
        request=inline_serializer(
            "ForceChangeStageRequest",
            fields={
                "stage_code": drf_serializers.CharField(),
                "reason": drf_serializers.CharField(required=False, default=""),
            },
        ),
        responses={
            200: DealDetailSerializer,
            400: OpenApiResponse(description="stage_code is required"),
            404: OpenApiResponse(description="Stage not found"),
        },
        tags=["CRM"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="force-change-stage",
        permission_classes=[IsAuthenticated, OperatorScoped],
    )
    def force_change_stage(self, request, pk=None):
        deal = self.get_object()
        stage_code = request.data.get("stage_code")
        reason = (request.data.get("reason") or "").strip()
        if not stage_code:
            return Response({"detail": "STAGE_CODE_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        if not reason:
            return Response({"detail": "REASON_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        deal, error = force_transition_deal_stage(
            deal,
            stage_code,
            actor=request.user,
            reason=reason,
        )
        if error:
            code = status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=code)
        return Response(DealDetailSerializer(deal).data)

    @extend_schema(
        summary="Export deal PDF",
        description=("Export PDF of the deal's active quote. " "Auto-generates the PDF if not yet created."),
        responses={
            (200, "application/pdf"): OpenApiResponse(description="PDF file download"),
            404: OpenApiResponse(description="No active quote"),
            500: OpenApiResponse(description="PDF generation failed"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="export-pdf")
    def export_pdf(self, request, pk=None):
        """Export PDF of the deal's active quote."""
        deal = self.get_object()
        quote = deal.active_quote
        if not quote:
            return Response({"error": "No active quote for this deal"}, status=status.HTTP_404_NOT_FOUND)
        if not quote.pdf_file:
            # Auto-generate PDF if not yet generated
            from crm.services import QuoteLifecycleService

            try:
                quote = QuoteLifecycleService.generate_pdf(quote.pk)
            except ValueError as exc:
                if str(exc) == "QUOTE_NOT_CLAIMED":
                    return Response({"error": "QUOTE_NOT_CLAIMED"}, status=status.HTTP_409_CONFLICT)
                return Response({"error": "Failed to generate PDF"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except (OSError, RuntimeError):
                return Response({"error": "Failed to generate PDF"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if not quote.pdf_file:
            return Response({"error": "PDF generation failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        from django.http import FileResponse

        return FileResponse(
            quote.pdf_file.open("rb"),
            content_type="application/pdf",
            as_attachment=True,
            filename=f"RailTech_Quote_{deal.id}.pdf",
        )


@extend_schema_view(
    list=extend_schema(summary="List deal stages", tags=["CRM"]),
)
class DealStageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DealStage.objects.all().order_by("sort_order", "name")
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{"code": s.code, "name": s.name} for s in self.get_queryset()]
        return Response(data)
