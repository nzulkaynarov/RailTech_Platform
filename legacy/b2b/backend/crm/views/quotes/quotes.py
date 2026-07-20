"""КП (`Quote`) ViewSet: CRUD, lifecycle actions (generate/send/approve/reject/
force-approve), the internal approval chain and PDF/export endpoints.

Split out of the monolithic ``crm/views/quotes.py`` (ARCH refactor) — behaviour
unchanged. NOTE (file-length exception): ``QuoteViewSet`` is a single cohesive DRF
ViewSet class (~560 lines) whose ``@action`` methods share the same authorization
vocabulary and lifecycle-service call pattern. Per the project's file-split rule, a
single class physically >500 lines may stay intact when splitting it across mixin
modules would harm readability — that applies here, so the class is kept whole.
"""

from django.db.models import Max
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.optimistic_locking import OptimisticLockingMixin
from core.permissions import IsCompanyMemberOrPlatformAdmin, OperatorScoped
from crm import services as crm_services
from crm.constants import QuoteStatusCode
from crm.models import Quote, QuoteStatus
from crm.serializers import QuoteSerializer
from crm.views._pdf import pdf_generating_response


def _chain_error_response(error):
    """Map a КП approval-chain service error code to an HTTP response."""
    forbidden = {"ROLE_NOT_PERMITTED", "QUOTE_SEND_NOT_ENTITLED", "SELLER_KYC_REQUIRED"}
    http_status = status.HTTP_403_FORBIDDEN if error in forbidden else status.HTTP_400_BAD_REQUEST
    return Response({"detail": error}, status=http_status)


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
class QuoteViewSet(OptimisticLockingMixin, viewsets.ModelViewSet):
    """
    CRUD for quotes (commercial proposals).

    Quote lifecycle: DRAFT -> SENT -> APPROVED / REJECTED.
    Includes PDF generation, send-to-client, approve, and reject actions.
    """

    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    # Operator sub-capability for the force-override action (ADR-0004 G1).
    operator_permissions = {"force_approve": "moderation.force_override"}

    def get_serializer_context(self):
        # Compute the (cost-gated) unit-economics block ONLY on the single-quote detail —
        # the КП builder reads it there. Off for list endpoints to avoid an items+charges N+1.
        ctx = super().get_serializer_context()
        ctx["include_economics"] = self.action == "retrieve"
        return ctx

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
        from accounts.services.permissions import seller_visible_deal_ids
        from crm.services.quotes import scope_quotes_for_viewer

        # Seller building КП across buyer заявки sees every quote — but only in a
        # seller context. In BUYER context the same user is scoped to its own deals.
        if getattr(user, "is_platform_admin", False):
            return queryset
        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            # Own КП only — a seller must not read a competitor's quote on a shared deal
            # (audit H1/#2). Shared helper = the same boundary the deal-nested prefetch uses.
            return scope_quotes_for_viewer(queryset.filter(deal_id__in=visible_deal_ids), user, self.request)
        # Buyer sees only quotes on their own company's deals.
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return queryset.filter(deal__company_id__in=user_company_ids)

    def perform_create(self, serializer):
        """Building a КП is a SELLER action: only a can_sell member (or superuser)
        may create one, and the server stamps prepared_by = the seller building it
        (anchoring the КП-owning company + approval chain). Auto-increments version."""
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import (
            can_edit_quote_pricing,
            is_platform_admin_viewer,
        )

        user = self.request.user
        if is_platform_admin_viewer(user):
            raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
        if not (getattr(user, "is_superuser", False) or can_edit_quote_pricing(user)):
            raise PermissionDenied("ONLY_SELLER_CAN_BUILD_QUOTE")
        deal = serializer.validated_data.get("deal")
        # SEC (audit #6): `deal` comes straight from the request body and bypasses the scoped
        # get_queryset, so bind it to the seller's routing — like QuoteItem/QuoteCharge create
        # (_assert_seller_owns_quote_deal). Without this a seller with pricing capability could
        # POST a rogue КП onto ANY deal id (incl. a competitor's), and version=max+1 makes it the
        # deal's active_quote → the buyer's total flips to 0 and the deal is polluted for the
        # legitimately-routed seller. Superuser bypasses; platform-admin already refused above.
        from accounts.services.permissions import seller_can_access_deal

        if deal is not None and not (
            getattr(user, "is_superuser", False) or seller_can_access_deal(user, self.request, deal.id)
        ):
            raise PermissionDenied("NO_ACCESS_TO_DEAL")
        version = (deal.quotes.aggregate(max_v=Max("version"))["max_v"] or 0) + 1 if deal else 1
        # A brand-new КП always starts the approval chain at DRAFT. Without this the
        # status FK stays NULL → QuoteApprovalChain renders no actions and the seller
        # is stuck with no way to submit the КП for review (the "тупик" bug).
        draft_status = QuoteStatus.objects.get(code=QuoteStatusCode.DRAFT)
        # Anchor the КП-owning seller company EXPLICITLY at create (audit H2) so ownership is
        # never re-derived from the preparer's primary membership downstream.
        from accounts.services.permissions import primary_seller_company_id

        seller_company_id = primary_seller_company_id(user)
        quote = serializer.save(
            version=version, prepared_by=user, status=draft_status, seller_company_id=seller_company_id
        )
        # Pre-fill КП-level defaults (Incoterm, валюта, НДС, маржа, срок действия) from the
        # building seller's CompanySettings — ONLY on create, never overwriting set values.
        if seller_company_id:
            from accounts.models import Company

            seller_company = Company.objects.filter(pk=seller_company_id).first()
            crm_services.apply_company_quote_defaults(quote, seller_company)

    def perform_update(self, serializer):
        """Editing КП-level settings (VAT rate, tax country, validity, currency) is a
        SELLER action — same gate as building line items / charges (can_edit_quote_pricing).
        Without this guard a buyer who can READ the КП via get_queryset could PATCH its
        pricing-relevant settings. The serializer coerces quote_currency (by code) and
        tax_country (by pk); changing vat_rate moves the VAT total, so recalc afterwards."""
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import (
            can_edit_quote_pricing,
            is_platform_admin_viewer,
        )

        user = self.request.user
        if is_platform_admin_viewer(user):
            raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
        if not (getattr(user, "is_superuser", False) or can_edit_quote_pricing(user)):
            raise PermissionDenied("ONLY_SELLER_CAN_BUILD_QUOTE")
        quote = serializer.instance
        if quote.frozen_at:
            raise PermissionDenied("QUOTE_FROZEN")
        serializer.save()
        # vat_rate feeds the VAT computation, so a settings change must re-aggregate
        # the КП totals (vat_amount / total_incl_vat) — Rule 8: logic in the service.
        from crm.services import QuoteCalculationService

        QuoteCalculationService.recalculate_quote(serializer.instance.pk)
        serializer.instance.refresh_from_db()

    @extend_schema(
        summary="Generate quote PDF",
        description=(
            "Validate the render guards, drop the stale PDF and enqueue an off-thread "
            "render (ARCH-03: WeasyPrint never runs in the request thread). Poll "
            "download-pdf until it stops returning 202."
        ),
        responses={
            202: OpenApiResponse(description="Render enqueued — poll download-pdf (Retry-After hint)"),
            409: OpenApiResponse(description="QUOTE_NOT_CLAIMED / FX_RATE_MISSING / QUOTE_BELOW_COST"),
            500: OpenApiResponse(description="PDF generation failed"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="generate-pdf")
    def generate_pdf(self, request, pk=None):
        """Re-render the КП PDF off-thread."""
        quote = self.get_object()
        from crm.services import QuoteLifecycleService

        try:
            # Claim + loss-prevention guards (HOLE 2) stay synchronous → 409, not 500.
            QuoteLifecycleService.assert_pdf_renderable(quote.pk)
        except ValueError as e:
            if str(e) in ("QUOTE_NOT_CLAIMED", "FX_RATE_MISSING", "QUOTE_BELOW_COST"):
                return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        # Explicit regenerate: drop the stale file reference first so a concurrent
        # download can't serve the outdated render while the task rebuilds it.
        if quote.pdf_file:
            quote.pdf_file = None
            quote.save(update_fields=["pdf_file"])
        return pdf_generating_response("quote", quote.pk)

    @extend_schema(
        summary="Send quote to client",
        description=(
            "Send an internally-approved (READY_TO_SEND) КП to the client. Freezes prices "
            "at current values. Allowed for the КП-owning company's SALES_MANAGER / OWNER, "
            "or a platform admin. When the КП is below the company margin floor (S7a) a "
            "non-empty `justification` is required (does not block the send, but is audited); "
            "otherwise the endpoint returns 400 BELOW_FLOOR_JUSTIFICATION_REQUIRED. The deal must "
            "have a reachable recipient (registered client or offline contact with an email), "
            "otherwise the endpoint returns 400 RECIPIENT_REQUIRED and nothing is sent."
        ),
        request=inline_serializer(
            name="QuoteSendToClientRequest",
            fields={
                "justification": drf_serializers.CharField(
                    required=False,
                    allow_blank=True,
                    max_length=500,
                    help_text="Обоснование отправки ниже минимальной маржи (S7a). Required only "
                    "when the КП is below the margin floor; ignored otherwise.",
                ),
            },
        ),
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(
                description="Quote not in READY_TO_SEND status, or below-floor send without "
                "justification (BELOW_FLOOR_JUSTIFICATION_REQUIRED), or JUSTIFICATION_TOO_LONG, "
                "or no reachable recipient (RECIPIENT_REQUIRED)."
            ),
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
        from accounts.services import assert_seller_can_operate
        from crm.services import QuoteLifecycleService
        from crm.services.quotes import can_send_quote_to_client

        quote = Quote.objects.select_related("status", "prepared_by", "deal").filter(pk=pk).first()
        if quote is None:
            return Response({"detail": "QUOTE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if not can_send_quote_to_client(request.user, quote):
            return _chain_error_response("ROLE_NOT_PERMITTED")
        # Paid-seller gate: sending the КП to the client is the monetised seller action.
        if sub_err := assert_seller_can_operate(request.user):
            return _chain_error_response(sub_err)
        # S7a below-floor justification (free text; length is validated in the service).
        justification = request.data.get("justification", "")
        if not isinstance(justification, str):
            justification = str(justification or "")
        try:
            quote = QuoteLifecycleService.send_to_client(int(pk), request.user, justification=justification)
        except ValueError as exc:
            code = str(exc)
            # Surface the specific loss-prevention / claim / below-floor errors instead of a generic status.
            return _chain_error_response(
                code
                if code
                in (
                    "QUOTE_BELOW_COST",
                    "QUOTE_NOT_CLAIMED",
                    "FX_RATE_MISSING",
                    "QUOTE_HAS_UNPRICED_LINES",
                    "QUOTE_SEND_NOT_ENTITLED",
                    "SELLER_KYC_REQUIRED",
                    "BELOW_FLOOR_JUSTIFICATION_REQUIRED",
                    "JUSTIFICATION_TOO_LONG",
                    "RECIPIENT_REQUIRED",
                )
                else "INVALID_STATUS"
            )
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Set delivery basis (Incoterm) and auto-apply its charge template",
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="set-delivery-basis", permission_classes=[IsAuthenticated])
    def set_delivery_basis(self, request, pk=None):
        """Seller picks the Incoterm; the basis template's charges auto-populate.

        Thin wrapper — all logic lives in crm.services.charges (Rule 8).
        """
        quote, err = crm_services.set_quote_delivery_basis(int(pk), request.data.get("delivery_basis"), request.user)
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err in ("ADMIN_VIEWER_CANNOT_ACT", "ONLY_SELLER_CAN_BUILD_QUOTE")
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": err}, status=http_status)
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Reorder КП charges (cascade order)",
        request=inline_serializer(
            "ChargesReorderRequest", fields={"order": drf_serializers.ListField(child=drf_serializers.IntegerField())}
        ),
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="charges-reorder", permission_classes=[IsAuthenticated])
    def charges_reorder(self, request, pk=None):
        """Reorder the КП's charges top-to-bottom (drives the cascade base). Thin wrapper (Rule 8)."""
        from crm.services.charges import reorder_quote_charges

        quote, err = reorder_quote_charges(int(pk), request.data.get("order") or [], request.user)
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err in ("ADMIN_VIEWER_CANNOT_ACT", "ONLY_SELLER_CAN_BUILD_QUOTE")
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": err}, status=http_status)
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Pricing-assist: suggest КП line costs from the seller's SupplierOffers",
        description=(
            "For each matched (product-linked) line, returns the seller's own active SupplierOffer "
            "price / currency / lead-time so the КП builder can autofill costs (ADR-0006 Move 3 — "
            "speed). Read-only suggestion; the seller reviews before applying. Cost-confidential: "
            "only the quote's own seller company sees its offers."
        ),
        responses={200: OpenApiResponse(description="{suggestions: [{item_id, product_id, base_price, ...}]}")},
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="pricing-assist", permission_classes=[IsAuthenticated])
    def pricing_assist(self, request, pk=None):
        """Thin wrapper (Rule 8) — suggest line costs from the seller's catalog offers."""
        from crm.services.pricing_assist import suggest_quote_pricing

        data, err = suggest_quote_pricing(int(pk), request.user)
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err == "ONLY_SELLER_CAN_BUILD_QUOTE"
                else status.HTTP_404_NOT_FOUND if err == "QUOTE_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": err}, status=http_status)
        return Response(data)

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

        try:
            quote = QuoteLifecycleService.approve_quote(quote.pk, request.user)
        except ValueError as exc:
            # Surface a clean 400 (incl. the P0-1 FSM error) instead of a 500.
            code = str(exc)
            return _chain_error_response(code if code == "FSM_TRANSITION_NOT_ALLOWED" else "INVALID_STATUS")
        return Response(self.get_serializer(quote).data)

    @staticmethod
    def _assert_buyer_can_buy(user, quote):
        """Return a 403 Response if `user` may not act as the deal's buyer, else None.

        Additive guard (defense-in-depth): legacy can_buy capability OR explicit
        quote.approve CompanyRole permission. has_explicit_company_role_perm skips
        the legacy can_buy fallback so only members with an intentional CompanyRole
        assignment pass through this new path (no accidental promotion).
        """
        from accounts.services.permissions import is_member_of, is_platform_admin_viewer
        from crm.services._params import has_explicit_company_role_perm

        if is_platform_admin_viewer(user):
            return Response({"detail": "ADMIN_VIEWER_CANNOT_ACT"}, status=status.HTTP_403_FORBIDDEN)
        company_id = quote.deal.company_id
        if not (
            getattr(user, "is_superuser", False)
            or is_member_of(user, company_id, capability="buy")
            or has_explicit_company_role_perm(user, company_id, "quote.approve")
        ):
            return Response({"detail": "MEMBER_REQUIRED_FOR_ACTION"}, status=status.HTTP_403_FORBIDDEN)
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

        try:
            quote = QuoteLifecycleService.reject_quote(quote.pk, request.user, reason)
        except ValueError as exc:
            code = str(exc)
            return _chain_error_response(code if code == "FSM_TRANSITION_NOT_ALLOWED" else "INVALID_STATUS")
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
    @action(
        detail=True,
        methods=["post"],
        url_path="force-approve",
        permission_classes=[IsAuthenticated, OperatorScoped],
    )
    def force_approve(self, request, pk=None):
        """Platform admin force-overrides quote status to APPROVED."""
        from crm.services import QuoteLifecycleService

        reason = request.data.get("reason", "")
        quote, error = QuoteLifecycleService.force_approve_quote(int(pk), request.user, reason)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
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
        summary="Act on a КП approval step (approve / reject)",
        request=inline_serializer(
            "ApprovalActRequest",
            fields={
                "step_id": drf_serializers.IntegerField(),
                "decision": drf_serializers.ChoiceField(choices=["APPROVE", "REJECT"]),
                "comment": drf_serializers.CharField(required=False, default=""),
            },
        ),
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(description="Wrong status/step"),
            403: OpenApiResponse(description="Role not permitted"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="approval-act", permission_classes=[IsAuthenticated])
    def approval_act(self, request, pk=None):
        """An approver approves or rejects their step in the КП approval chain."""
        from crm.services.approvals import act_on_step

        step_id = request.data.get("step_id")
        decision = (request.data.get("decision") or "").upper()
        comment = request.data.get("comment", "")
        if decision not in ("APPROVE", "REJECT"):
            return _chain_error_response("INVALID_DECISION")
        if not step_id:
            return _chain_error_response("STEP_NOT_FOUND")
        quote, error = act_on_step(int(step_id), request.user, decision, comment)
        if error:
            return _chain_error_response(error)
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Recall a КП from approval back to DRAFT (submitter / head)",
        responses={
            200: QuoteSerializer,
            400: OpenApiResponse(description="Wrong status"),
            403: OpenApiResponse(description="Not permitted"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="recall", permission_classes=[IsAuthenticated])
    def recall(self, request, pk=None):
        """Pull a КП back out of the approval chain to edit it (PENDING_APPROVAL → DRAFT)."""
        from crm.services.approvals import recall_quote

        quote, error = recall_quote(int(pk), request.user)
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
        description="Download the persisted КП PDF; 202 + off-thread render when it is not ready yet.",
        responses={
            (200, "application/pdf"): OpenApiResponse(description="PDF file"),
            202: OpenApiResponse(description="PDF rendering off-thread — retry after Retry-After seconds"),
            409: OpenApiResponse(description="QUOTE_NOT_CLAIMED / FX_RATE_MISSING / QUOTE_BELOW_COST"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        """Download the generated PDF."""
        quote = self.get_object()
        if not quote.pdf_file:
            # The КП PDF is rendered asynchronously after the quote is sent (F1.6), so a
            # download may race ahead of the Celery task — or arrive while the worker is
            # down. ARCH-03: enqueue + 202 instead of running WeasyPrint inline; only the
            # cheap render guards run synchronously so guard failures still 409.
            from crm.services import QuoteLifecycleService

            try:
                QuoteLifecycleService.assert_pdf_renderable(quote.pk)
            except ValueError as exc:
                if str(exc) in ("QUOTE_NOT_CLAIMED", "FX_RATE_MISSING", "QUOTE_BELOW_COST"):
                    return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
                return Response({"detail": "PDF generation failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return pdf_generating_response("quote", quote.pk)

        from django.http import FileResponse

        return FileResponse(
            quote.pdf_file.open("rb"),
            content_type="application/pdf",
            as_attachment=True,
            filename=quote.pdf_file.name.split("/")[-1],
        )

    @extend_schema(
        summary="Export quote in a chosen format (pdf | xlsx | csv)",
        description=(
            "On-demand, user-chosen export of the КП. ?export_format=pdf returns the CLIENT "
            "projection (no seller cost/margin); ?export_format=xlsx|csv returns the seller line "
            "table, including cost/margin columns only when the requester may view КП costs. "
            "The key is export_format (NOT format) — DRF reserves ?format for content-negotiation."
        ),
        parameters=[
            OpenApiParameter(
                name="export_format",
                description="Export format: pdf (default), xlsx, or csv.",
                required=False,
                type=str,
                enum=["pdf", "xlsx", "csv"],
            )
        ],
        responses={
            200: OpenApiResponse(description="Rendered file (PDF / XLSX / CSV)"),
            202: OpenApiResponse(description="PDF rendering off-thread (ARCH-03) — retry after Retry-After seconds"),
            400: OpenApiResponse(description="Unsupported format"),
            409: OpenApiResponse(description="QUOTE_NOT_CLAIMED / FX_RATE_MISSING / QUOTE_BELOW_COST"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="export")
    def export(self, request, pk=None):
        """Thin wrapper — format dispatch + cost gating live in crm.views.exports."""
        from crm.views.exports import handle_quote_export

        return handle_quote_export(request, self.get_object())
