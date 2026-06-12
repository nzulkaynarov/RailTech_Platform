from django.db.models import Max
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsCompanyMemberOrPlatformAdmin, IsPlatformAdmin
from crm import services as crm_services
from crm.constants import QuoteStatusCode
from crm.models import Quote, QuoteItem, QuoteStatus
from crm.serializers import QuoteItemSerializer, QuoteSerializer


def _chain_error_response(error):
    """Map a КП approval-chain service error code to an HTTP response."""
    http_status = status.HTTP_403_FORBIDDEN if error == "ROLE_NOT_PERMITTED" else status.HTTP_400_BAD_REQUEST
    return Response({"error": error}, status=http_status)


@extend_schema_view(
    list=extend_schema(
        summary="List quotes",
        description="Returns quotes accessible to the current user with items.",
        tags=["CRM"],
    ),
    create=extend_schema(summary="Create quote", tags=["CRM"]),
    retrieve=extend_schema(
        summary="Get quote details",
        description="Returns full quote details including all line items.",
        tags=["CRM"],
    ),
    update=extend_schema(summary="Update quote", tags=["CRM"]),
    partial_update=extend_schema(summary="Partially update quote", tags=["CRM"]),
    destroy=extend_schema(summary="Delete quote", tags=["CRM"]),
)
class QuoteViewSet(viewsets.ModelViewSet):
    """
    CRUD for quotes (commercial proposals).

    Quote lifecycle: DRAFT -> SENT -> APPROVED / REJECTED.
    Includes PDF generation, send-to-client, approve, and reject actions.
    """

    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Quote.objects.none()
        user = self.request.user
        queryset = (
            Quote.objects.all()
            .select_related("deal", "deal__company", "deal__stage", "status")
            .prefetch_related(
                "items",
                "items__product",
                "items__product__domain_type",
                "items__offer",
                "items__offer__supplier",
                "items__frozen_currency",
            )
        )
        from accounts.services.permissions import is_seller

        if user.is_platform_admin:
            return queryset
        # The seller builds КП across all buyer заявки → sees every quote.
        if is_seller(user):
            return queryset
        # Buyer sees only quotes on their own company's deals.
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return queryset.filter(deal__company_id__in=user_company_ids)

    def perform_create(self, serializer):
        """Building a КП is a SELLER action: only a can_sell member (or superuser)
        may create one, and the server stamps prepared_by = the seller building it
        (anchoring the КП-owning company + approval chain). Auto-increments version."""
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import is_platform_admin_viewer, is_seller

        user = self.request.user
        if is_platform_admin_viewer(user):
            raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
        if not (getattr(user, "is_superuser", False) or is_seller(user)):
            raise PermissionDenied("ONLY_SELLER_CAN_BUILD_QUOTE")
        deal = serializer.validated_data.get("deal")
        version = (deal.quotes.aggregate(max_v=Max("version"))["max_v"] or 0) + 1 if deal else 1
        # A brand-new КП always starts the approval chain at DRAFT. Without this the
        # status FK stays NULL → QuoteApprovalChain renders no actions and the seller
        # is stuck with no way to submit the КП for review (the "тупик" bug).
        draft_status = QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT)
        serializer.save(version=version, prepared_by=user, status=draft_status)

    @extend_schema(
        summary="Generate quote PDF",
        description="Generate a PDF file for the quote using WeasyPrint.",
        responses={
            200: OpenApiResponse(description="PDF generated, URL returned"),
            500: OpenApiResponse(description="PDF generation failed"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="generate-pdf")
    def generate_pdf(self, request, pk=None):
        """Generate PDF for a quote."""
        quote = self.get_object()
        from crm.services import QuoteLifecycleService

        try:
            quote = QuoteLifecycleService.generate_pdf(quote.pk)
            return Response(
                {
                    "status": "PDF generated",
                    "url": (request.build_absolute_uri(quote.pdf_file.url) if quote.pdf_file else None),
                }
            )
        except (OSError, ValueError, RuntimeError) as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        summary="Send quote to client",
        description=(
            "Send an internally-approved (READY_TO_SEND) КП to the client. Freezes prices "
            "at current values. Allowed for the КП-owning company's SALES_MANAGER / OWNER, "
            "or a platform admin."
        ),
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(description="Quote not in READY_TO_SEND status"),
            403: OpenApiResponse(description="Role not permitted"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="send-to-client", permission_classes=[IsAuthenticated])
    def send_to_client(self, request, pk=None):
        """Send an internally-approved КП to the client. Freezes prices.

        Authorization is anchored to the КП's owning company (the seller team that
        ran the approval chain), so this can't reuse the deal-company-scoped
        get_queryset — it fetches the quote directly like the chain actions do.
        """
        from crm.services import QuoteLifecycleService
        from crm.services.quotes import can_send_quote_to_client

        quote = Quote.objects.select_related("status", "prepared_by", "deal").filter(pk=pk).first()
        if quote is None:
            return Response({"error": "QUOTE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if not can_send_quote_to_client(request.user, quote):
            return _chain_error_response("ROLE_NOT_PERMITTED")
        try:
            quote = QuoteLifecycleService.send_to_client(int(pk), request.user)
        except ValueError:
            return _chain_error_response("INVALID_STATUS")
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Approve quote",
        description="Client approves the quote. Only the client's company members or staff can approve.",
        responses={
            200: QuoteSerializer,
            403: OpenApiResponse(description="Not authorized"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        """Client approves the quote — buyer-side can_buy member only.

        Approving moves the deal to CONTRACT_SIGNED, so it's a commitment that
        must carry can_buy (parity with accept-bid / sign-contract). Platform
        admins act via force-approve, never here (ADMIN_VIEWER_CANNOT_ACT)."""
        quote = self.get_object()
        denied = self._assert_buyer_can_buy(request.user, quote)
        if denied:
            return denied
        from crm.services import QuoteLifecycleService

        quote = QuoteLifecycleService.approve_quote(quote.pk, request.user)
        return Response(self.get_serializer(quote).data)

    @staticmethod
    def _assert_buyer_can_buy(user, quote):
        """Return a 403 Response if `user` may not act as the deal's buyer, else None."""
        from accounts.services.permissions import is_member_of, is_platform_admin_viewer

        if is_platform_admin_viewer(user):
            return Response({"error": "ADMIN_VIEWER_CANNOT_ACT"}, status=status.HTTP_403_FORBIDDEN)
        if not (getattr(user, "is_superuser", False) or is_member_of(user, quote.deal.company_id, capability="buy")):
            return Response({"error": "MEMBER_REQUIRED_FOR_ACTION"}, status=status.HTTP_403_FORBIDDEN)
        return None

    @extend_schema(
        summary="Reject quote",
        description="Client rejects the quote with an optional reason.",
        request=inline_serializer(
            "RejectQuoteRequest",
            fields={
                "reason": drf_serializers.CharField(required=False, default=""),
            },
        ),
        responses={
            200: QuoteSerializer,
            403: OpenApiResponse(description="Not authorized"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        """Client rejects the quote — buyer-side can_buy member only."""
        quote = self.get_object()
        denied = self._assert_buyer_can_buy(request.user, quote)
        if denied:
            return denied
        reason = request.data.get("reason", "")
        from crm.services import QuoteLifecycleService

        quote = QuoteLifecycleService.reject_quote(quote.pk, request.user, reason)
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Force-approve quote (Platform Admin escalation)",
        description="Bypass status guard and mark quote as APPROVED. ADMIN role required. Audit-logged with [FORCE_ADMIN].",
        request=inline_serializer(
            "ForceApproveQuoteRequest",
            fields={
                "reason": drf_serializers.CharField(required=True),
            },
        ),
        responses={200: QuoteSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="force-approve")
    def force_approve(self, request, pk=None):
        """Platform admin force-overrides quote status to APPROVED."""
        from crm.services import QuoteLifecycleService

        reason = request.data.get("reason", "")
        quote, error = QuoteLifecycleService.force_approve_quote(int(pk), request.user, reason)
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(quote).data)

    # ── Internal approval chain (документооборот) ──────────────────────────
    # Role gating lives in the service (anchored to the КП's owning company), so
    # these only need IsAuthenticated; the service returns ROLE_NOT_PERMITTED → 403.

    @extend_schema(
        summary="Submit КП into the approval chain (SALES_MANAGER)",
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(description="Wrong status"),
            403: OpenApiResponse(description="Role not permitted"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="submit-for-review", permission_classes=[IsAuthenticated])
    def submit_for_review(self, request, pk=None):
        from crm.services import QuoteLifecycleService

        quote, error = QuoteLifecycleService.submit_for_review(int(pk), request.user)
        if error:
            return _chain_error_response(error)
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Confirm trade review (FOREIGN_TRADE_SPECIALIST / ВЭД)",
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(description="Wrong status"),
            403: OpenApiResponse(description="Role not permitted"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="confirm-trade-review", permission_classes=[IsAuthenticated])
    def confirm_trade_review(self, request, pk=None):
        from crm.services import QuoteLifecycleService

        quote, error = QuoteLifecycleService.confirm_trade_review(int(pk), request.user)
        if error:
            return _chain_error_response(error)
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Approve КП internally (DIRECTOR)",
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(description="Wrong status"),
            403: OpenApiResponse(description="Role not permitted"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="director-approve", permission_classes=[IsAuthenticated])
    def director_approve(self, request, pk=None):
        from crm.services import QuoteLifecycleService

        quote, error = QuoteLifecycleService.director_approve(int(pk), request.user)
        if error:
            return _chain_error_response(error)
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Send КП back to sales for rework (ВЭД / DIRECTOR)",
        request=inline_serializer(
            "SendBackQuoteRequest", fields={"reason": drf_serializers.CharField(required=False, default="")}
        ),
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(description="Wrong status"),
            403: OpenApiResponse(description="Role not permitted"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="send-back", permission_classes=[IsAuthenticated])
    def send_back(self, request, pk=None):
        from crm.services import QuoteLifecycleService

        reason = request.data.get("reason", "")
        quote, error = QuoteLifecycleService.send_back(int(pk), request.user, reason)
        if error:
            return _chain_error_response(error)
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="My КП approval queue",
        description="Quotes in the company(ies) I belong to that are waiting on my workspace role's step.",
        responses={200: QuoteSerializer(many=True)},
        tags=["CRM"],
    )
    @action(detail=False, methods=["get"], url_path="my-approval-queue", permission_classes=[IsAuthenticated])
    def my_approval_queue(self, request):
        from crm.services.quotes import approval_queue_for

        queryset = approval_queue_for(request.user)
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

    @extend_schema(
        summary="Download quote PDF",
        description="Download the previously generated PDF file for a quote.",
        responses={
            (200, "application/pdf"): OpenApiResponse(description="PDF file"),
            404: OpenApiResponse(description="PDF not generated yet"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        """Download the generated PDF."""
        quote = self.get_object()
        if not quote.pdf_file:
            return Response(
                {"error": "PDF not generated yet"},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.http import FileResponse

        return FileResponse(
            quote.pdf_file.open("rb"),
            content_type="application/pdf",
            as_attachment=True,
            filename=quote.pdf_file.name.split("/")[-1],
        )


@extend_schema_view(
    list=extend_schema(
        summary="List quote items",
        description="Returns quote line items accessible to the current user.",
        tags=["CRM"],
    ),
    create=extend_schema(
        summary="Create quote item",
        description="Add a line item to a quote.",
        tags=["CRM"],
    ),
    retrieve=extend_schema(summary="Get quote item", tags=["CRM"]),
    update=extend_schema(summary="Update quote item", tags=["CRM"]),
    partial_update=extend_schema(summary="Partially update quote item", tags=["CRM"]),
    destroy=extend_schema(summary="Delete quote item", tags=["CRM"]),
)
class QuoteItemViewSet(viewsets.ModelViewSet):
    """CRUD for quote line items (products, quantities, pricing)."""

    serializer_class = QuoteItemSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_fields = {
        "quote__deal_id": ["exact"],
        "product": ["isnull", "exact"],
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return QuoteItem.objects.none()
        user = self.request.user
        from accounts.services.permissions import is_seller

        queryset = QuoteItem.objects.all().select_related(
            "product", "product__domain_type", "quote", "offer", "offer__supplier", "frozen_currency"
        )
        if user.is_platform_admin or is_seller(user):
            return queryset
        # Buyer sees line items only on their own deals (read-only — see _assert_seller).
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return queryset.filter(quote__deal__company_id__in=user_company_ids)

    def _assert_seller(self):
        """Building/editing КП line items is a seller action. Raise 403 otherwise."""
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import is_platform_admin_viewer, is_seller

        user = self.request.user
        if is_platform_admin_viewer(user):
            raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
        if not (getattr(user, "is_superuser", False) or is_seller(user)):
            raise PermissionDenied("ONLY_SELLER_CAN_BUILD_QUOTE")

    def perform_create(self, serializer):
        self._assert_seller()
        serializer.save()

    def perform_update(self, serializer):
        self._assert_seller()
        serializer.save()

    def perform_destroy(self, instance):
        self._assert_seller()
        instance.delete()

    @extend_schema(
        summary="Manually reassign product for a quote item",
        tags=["CRM"],
        request=inline_serializer(
            "ReassignProduct",
            fields={
                "product_id": drf_serializers.IntegerField(allow_null=True),
            },
        ),
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="reassign-product",
        permission_classes=[IsAuthenticated, IsPlatformAdmin],
    )
    def reassign_product(self, request, pk=None):
        product_id = request.data.get("product_id")
        item, err = crm_services.reassign_quote_item_product(
            int(pk),
            request.user,
            product_id=int(product_id) if product_id else None,
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(QuoteItemSerializer(item).data)

    @extend_schema(summary="Get top-N smart-match candidates for this item", tags=["CRM"])
    @action(
        detail=True, methods=["get"], url_path="match-candidates", permission_classes=[IsAuthenticated, IsPlatformAdmin]
    )
    def match_candidates(self, request, pk=None):
        from sourcing.services import smart_match_candidates

        item = self.get_object()
        raw = item.imported_raw_name or (item.product.name if item.product else "")
        domain_hint = item.product.domain_type.code if (item.product and item.product.domain_type) else None
        candidates = smart_match_candidates(raw, limit=5, domain_hint=domain_hint)
        return Response({"raw": raw, "candidates": candidates})


@extend_schema_view(
    list=extend_schema(summary="List quote statuses", tags=["CRM"]),
)
class QuoteStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = QuoteStatus.objects.all().order_by("sort_order", "name")
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{"code": s.code, "name": s.name} for s in self.get_queryset()]
        return Response(data)
