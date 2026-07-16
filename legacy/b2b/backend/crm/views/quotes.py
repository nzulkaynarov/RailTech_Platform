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
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.file_streaming import stream_file_field
from core.optimistic_locking import OptimisticLockingMixin
from core.permissions import IsCompanyMemberOrPlatformAdmin, OperatorScoped
from crm import services as crm_services
from crm.constants import QuoteStatusCode
from crm.models import (
    ChargeTemplate,
    ChargeType,
    Quote,
    QuoteCharge,
    QuoteItem,
    QuoteStatus,
)
from crm.serializers import (
    ChargeTemplateSerializer,
    ChargeTypeSerializer,
    QuoteChargeSerializer,
    QuoteItemSerializer,
    QuoteSerializer,
)
from crm.views._pdf import pdf_generating_response


def _chain_error_response(error):
    """Map a КП approval-chain service error code to an HTTP response."""
    forbidden = {"ROLE_NOT_PERMITTED", "QUOTE_SEND_NOT_ENTITLED", "SELLER_KYC_REQUIRED"}
    http_status = status.HTTP_403_FORBIDDEN if error in forbidden else status.HTTP_400_BAD_REQUEST
    return Response({"detail": error}, status=http_status)


# ARCH-03: race-window polling hints for the public КП PDF. When a client opens the emailed
# link before the off-thread render (F1.6) has landed, we ask them to retry rather than run
# WeasyPrint inline in this anonymous request thread. Small polling constants, not business data.
PUBLIC_PDF_RETRY_AFTER_SECONDS = 2
PUBLIC_PDF_MAX_AUTO_RETRIES = 5


class PublicQuoteView(APIView):
    """Unauthenticated КП view/download by secret token (client base, CB-public-link).

    Lets an offline or registered client open the КП the seller emailed them WITHOUT a
    login. Streams the CLIENT projection PDF only (quote_pdf.html exposes no margin/cost/
    charges). Only a SENT (frozen) КП with a token is reachable; an unknown token 404s.
    Rate-limited to blunt token brute-forcing despite the 256-bit space.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_quote"

    @extend_schema(
        summary="Public КП view/download by token",
        responses={
            (200, "application/pdf"): OpenApiResponse(description="КП PDF (client projection)"),
            202: OpenApiResponse(description="PDF still rendering off-thread — retry after Retry-After seconds"),
            404: OpenApiResponse(description="Unknown or not-yet-sent token"),
            410: OpenApiResponse(
                description="Public link revoked or expired (QUOTE_LINK_REVOKED / QUOTE_LINK_EXPIRED)"
            ),
        },
        tags=["CRM"],
    )
    def get(self, request, token):
        from crm.services.quotes import public_quote_gate

        quote = Quote.objects.select_related("deal", "status").filter(public_access_token=token).first()
        # Reachability gate (Rule 8): unknown/not-yet-sent → 404 (no info leak); revoked or
        # lapsed (EXPIRED / valid_until / token TTL, audit #17) → 410 GONE. Live → fall through.
        gate_error = public_quote_gate(quote)
        if gate_error == "NOT_FOUND":
            return Response({"detail": gate_error}, status=status.HTTP_404_NOT_FOUND)
        if gate_error is not None:
            return Response({"detail": gate_error}, status=status.HTTP_410_GONE)
        if not quote.pdf_file:
            # ARCH-03: NEVER run a synchronous WeasyPrint render in this AllowAny/anonymous
            # request thread — a full sync render here is a DoS-amplification surface. The КП PDF
            # is normally already persisted off-thread on send (F1.6 → send_quote_email); only the
            # race window (client opens the link before the celery task lands) or a downed worker
            # reaches this branch. Enqueue the idempotent render task (it no-ops if the file already
            # exists) and ask the client to retry, instead of rendering inline.
            from crm.tasks import render_document_pdf

            render_document_pdf.delay("quote", quote.pk)
            return self._pdf_generating_response(request)
        return stream_file_field(quote.pdf_file)

    @staticmethod
    def _pdf_generating_response(request):
        """202 telling the caller the PDF is still rendering off-thread.

        Content-negotiated: the emailed link opens THIS endpoint directly in a browser (there is
        no SPA page in front of it), so a browser (Accept: text/html) gets a small self-refreshing
        interstitial that auto-retries a few times then offers a manual «Обновить»; an API/JSON
        client gets a compact JSON body. Both carry a Retry-After header.
        """
        from django.shortcuts import render

        retry_after = PUBLIC_PDF_RETRY_AFTER_SECONDS
        wants_html = "text/html" in request.META.get("HTTP_ACCEPT", "")
        if wants_html:
            try:
                attempt = max(0, int(request.GET.get("r", 0)))
            except (TypeError, ValueError):
                attempt = 0
            response = render(
                request,
                "public/quote_generating.html",
                {
                    "retry_after": retry_after,
                    "auto_retry": attempt < PUBLIC_PDF_MAX_AUTO_RETRIES,
                    "next_query": f"?r={attempt + 1}",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        else:
            response = Response(
                {"detail": "GENERATING", "retry_after": retry_after},
                status=status.HTTP_202_ACCEPTED,
            )
        response["Retry-After"] = str(retry_after)
        return response


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
        try:
            quote = QuoteLifecycleService.send_to_client(int(pk), request.user)
        except ValueError as exc:
            code = str(exc)
            # Surface the specific loss-prevention / claim errors instead of a generic status.
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
            "On-demand, user-chosen export of the КП. ?format=pdf returns the CLIENT "
            "projection (no seller cost/margin); ?format=xlsx|csv returns the seller line "
            "table, including cost/margin columns only when the requester may view КП costs."
        ),
        parameters=[
            OpenApiParameter(
                name="format",
                description="Export format: pdf (default), xlsx, or csv.",
                required=False,
                type=str,
                enum=["pdf", "xlsx", "csv"],
            )
        ],
        responses={
            200: OpenApiResponse(description="Rendered file (PDF / XLSX / CSV)"),
            400: OpenApiResponse(description="Unsupported format"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="export")
    def export(self, request, pk=None):
        """Thin wrapper — format dispatch + cost gating live in crm.views.exports."""
        from crm.views.exports import handle_quote_export

        return handle_quote_export(request, self.get_object())


def _assert_seller_owns_quote_deal(request, quote):
    """A seller may only WRITE to a quote whose deal is routed to them. `perform_create`
    takes the target `quote` from the request body and bypasses the scoped get_queryset +
    object permission, so without this a seller could POST items/charges onto a COMPETITOR's
    КП (review 2026-06-25, CRITICAL #1). Superuser bypasses; platform-admin is already
    refused upstream by _assert_seller (ADMIN_VIEWER_CANNOT_ACT)."""
    from rest_framework.exceptions import PermissionDenied

    from accounts.services.permissions import seller_can_access_deal

    user = request.user
    if getattr(user, "is_superuser", False):
        return
    if quote is None or not seller_can_access_deal(user, request, quote.deal_id):
        raise PermissionDenied("NO_ACCESS_TO_DEAL")


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
    # The КП builder grid renders EVERY line of a quote and recomputes economics over
    # all of them; the global DRF PAGE_SIZE=20 silently truncated the grid to the first
    # 20 rows while totals still reflected the full set — data loss for the seller.
    # A quote is a bounded document (line items per КП), so returning the full list is safe.
    pagination_class = None
    filterset_fields = {
        "quote__deal_id": ["exact"],
        "product": ["isnull", "exact"],
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return QuoteItem.objects.none()
        user = self.request.user
        from accounts.services.permissions import seller_visible_deal_ids

        queryset = QuoteItem.objects.all().select_related(
            "product", "product__domain_type", "quote", "offer", "offer__supplier", "frozen_currency"
        )
        if getattr(user, "is_platform_admin", False):
            return queryset
        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            from accounts.models import CompanyMember
            from accounts.services.permissions import (
                SELLER_COMPANY_TYPES,
                seller_acting_company_ids,
            )

            # The seller sees items/charges on deals routed to them. Audit H1 (no cross-seller
            # leak): hide a quote ONLY when it was prepared by a COMPETING seller company. The
            # buyer's request lines and the seller's КП are the SAME quote in this model, and
            # that quote is created by the BUYER (or left unassigned) — so scoping by
            # prepared_by's *seller* company alone wrongly hid the seller's own КП and made
            # pricing un-saveable (404 on item PATCH → subtotal stuck at 0). Exclude only
            # quotes whose prepared_by belongs to another seller company.
            seller_ids = seller_acting_company_ids(user, self.request) or set()
            # Dual-membership edge: a user who belongs to BOTH the viewer's own seller
            # company AND a competing one would otherwise land in competing_preparer_ids
            # and hide their OWN company's legitimately-prepared КП from their own viewers.
            # Subtract members of the viewer's OWN seller companies so only PURELY-competing
            # preparers are excluded.
            own_member_ids = CompanyMember.objects.filter(is_active=True, company_id__in=seller_ids).values_list(
                "user_id", flat=True
            )
            competing_preparer_ids = (
                CompanyMember.objects.filter(is_active=True, company__types__code__in=SELLER_COMPANY_TYPES)
                .exclude(company_id__in=seller_ids)
                .exclude(user_id__in=own_member_ids)
                .values_list("user_id", flat=True)
            )
            return (
                queryset.filter(quote__deal_id__in=visible_deal_ids)
                .exclude(quote__prepared_by_id__in=competing_preparer_ids)
                .distinct()
            )
        # Buyer sees line items only on their own deals (read-only — see _assert_seller).
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return queryset.filter(quote__deal__company_id__in=user_company_ids)

    def _assert_seller(self):
        """Building/editing КП line items is a seller action. Raise 403 otherwise."""
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

    def _is_seller_write(self) -> bool:
        from accounts.services.permissions import is_seller

        user = self.request.user
        return bool(getattr(user, "is_superuser", False) or is_seller(user))

    def perform_create(self, serializer):
        # Manual item creation on a КП is a seller action. Buyers add request
        # rows through POST /crm/deals/{id}/add-request-item/ instead (it
        # get-or-creates the DRAFT quote and restricts fields to name + qty).
        self._assert_seller()
        _assert_seller_owns_quote_deal(self.request, serializer.validated_data.get("quote"))
        serializer.save()

    def perform_update(self, serializer):
        if self._is_seller_write():
            self._assert_seller()
            serializer.save()
            return
        # Buyer editing their own still-open request — name + quantity only,
        # never pricing. The service re-checks can_buy + the editable window.
        crm_services.buyer_update_request_item(
            self.request.user,
            serializer.instance,
            name=serializer.validated_data.get("imported_raw_name"),
            quantity=serializer.validated_data.get("quantity"),
            unit=serializer.validated_data.get("unit"),
            unit_code=serializer.validated_data.get("unit_code"),
            note=serializer.validated_data.get("note"),
            mpn=serializer.validated_data.get("mpn"),
            name_canonical=serializer.validated_data.get("name_canonical"),
        )
        serializer.instance.refresh_from_db()

    def perform_destroy(self, instance):
        if self._is_seller_write():
            self._assert_seller()
            instance.delete()
            return
        crm_services.buyer_remove_request_item(self.request.user, instance)

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
        permission_classes=[IsAuthenticated],
    )
    def reassign_product(self, request, pk=None):
        # P0-2: re-matching an item to a catalog product is a SELLER action (КП assembly), NOT
        # platform-admin-only — the dialog renders on the seller's own КП page. _assert_seller
        # gates "is a seller"; get_object scopes to the seller's own visible items (a buyer can't
        # reach another tenant's item, and a buyer hitting their own item is refused by _assert_seller).
        self._assert_seller()
        item = self.get_object()
        product_id = request.data.get("product_id")
        updated, err = crm_services.reassign_quote_item_product(
            item.id,
            request.user,
            product_id=int(product_id) if product_id else None,
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(QuoteItemSerializer(updated).data)

    @extend_schema(
        summary="Bulk-update КП line items in one transaction",
        description=(
            "Save many edited КП lines atomically (P0-4). ALL-OR-NOTHING: if any line is "
            "invalid, nothing is saved and per-row errors are returned; on success the cascade "
            "and totals are recalculated ONCE and the updated lines are returned. Same guards / "
            "field validation as the single-item PATCH. Seller action."
        ),
        request=inline_serializer(
            "BulkUpdateQuoteItemsRequest",
            fields={
                "quote": drf_serializers.IntegerField(),
                "items": drf_serializers.ListField(child=drf_serializers.DictField()),
            },
        ),
        responses={
            200: QuoteItemSerializer(many=True),
            400: OpenApiResponse(
                description="QUOTE_ITEMS_BULK_INVALID (with per-row `rows`) / QUOTE_ITEMS_BULK_EMPTY / "
                "QUOTE_ITEMS_BULK_TOO_LARGE / QUOTE_FROZEN"
            ),
            403: OpenApiResponse(description="ADMIN_VIEWER_CANNOT_ACT / ONLY_SELLER_CAN_BUILD_QUOTE"),
            404: OpenApiResponse(description="QUOTE_NOT_FOUND"),
        },
        tags=["CRM"],
    )
    @action(detail=False, methods=["post"], url_path="bulk-update", permission_classes=[IsAuthenticated])
    def bulk_update(self, request):
        """Thin wrapper (Rule 8) — all logic in crm.services.quotes.bulk_update_quote_items."""
        from crm.services.quotes import bulk_update_quote_items

        items, error, rows = bulk_update_quote_items(
            request.user, request.data.get("quote"), request.data.get("items"), request
        )
        if error == "QUOTE_ITEMS_BULK_INVALID":
            return Response({"detail": error, "rows": rows}, status=status.HTTP_400_BAD_REQUEST)
        if error:
            http_status = {
                "ADMIN_VIEWER_CANNOT_ACT": status.HTTP_403_FORBIDDEN,
                "ONLY_SELLER_CAN_BUILD_QUOTE": status.HTTP_403_FORBIDDEN,
                "QUOTE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            }.get(error, status.HTTP_400_BAD_REQUEST)
            return Response({"detail": error}, status=http_status)
        return Response(self.get_serializer(items, many=True).data)

    @extend_schema(
        summary="Bulk-create КП line items in one transaction",
        description=(
            "Insert many new КП lines atomically (Excel-paste). ALL-OR-NOTHING: if any row is "
            "invalid, nothing is saved and per-row errors are returned; on success the cascade "
            "and totals are recalculated ONCE and the created lines are returned (201). Same "
            "field validation as the single-item create; every row needs a non-empty "
            "imported_raw_name. Seller action."
        ),
        request=inline_serializer(
            "BulkCreateQuoteItemsRequest",
            fields={
                "quote": drf_serializers.IntegerField(),
                "items": drf_serializers.ListField(child=drf_serializers.DictField()),
            },
        ),
        responses={
            201: QuoteItemSerializer(many=True),
            400: OpenApiResponse(
                description="QUOTE_ITEMS_BULK_INVALID (with per-row `rows`) / QUOTE_ITEMS_BULK_EMPTY / "
                "QUOTE_ITEMS_BULK_TOO_LARGE / QUOTE_FROZEN"
            ),
            403: OpenApiResponse(description="ADMIN_VIEWER_CANNOT_ACT / ONLY_SELLER_CAN_BUILD_QUOTE"),
            404: OpenApiResponse(description="QUOTE_NOT_FOUND"),
        },
        tags=["CRM"],
    )
    @action(detail=False, methods=["post"], url_path="bulk-create", permission_classes=[IsAuthenticated])
    def bulk_create(self, request):
        """Thin wrapper (Rule 8) — all logic in crm.services.quotes.bulk_create_quote_items."""
        from crm.services.quotes import bulk_create_quote_items

        items, error, rows = bulk_create_quote_items(
            request.user, request.data.get("quote"), request.data.get("items"), request
        )
        if error == "QUOTE_ITEMS_BULK_INVALID":
            return Response({"detail": error, "rows": rows}, status=status.HTTP_400_BAD_REQUEST)
        if error:
            http_status = {
                "ADMIN_VIEWER_CANNOT_ACT": status.HTTP_403_FORBIDDEN,
                "ONLY_SELLER_CAN_BUILD_QUOTE": status.HTTP_403_FORBIDDEN,
                "QUOTE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
            }.get(error, status.HTTP_400_BAD_REQUEST)
            return Response({"detail": error}, status=http_status)
        return Response(self.get_serializer(items, many=True).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Get top-N smart-match candidates for this item", tags=["CRM"])
    @action(detail=True, methods=["get"], url_path="match-candidates", permission_classes=[IsAuthenticated])
    def match_candidates(self, request, pk=None):
        from sourcing.services import smart_match_candidates

        self._assert_seller()
        item = self.get_object()
        raw = item.imported_raw_name or (item.product.name if item.product else "")
        domain_hint = item.product.domain_type.code if (item.product and item.product.domain_type) else None
        candidates = smart_match_candidates(raw, limit=5, domain_hint=domain_hint)
        return Response({"raw": raw, "candidates": candidates})


@extend_schema_view(
    list=extend_schema(summary="List КП-level expense items / discounts", tags=["CRM"]),
    create=extend_schema(summary="Add КП-level expense item / discount", tags=["CRM"]),
    destroy=extend_schema(summary="Remove КП-level expense item / discount", tags=["CRM"]),
)
class QuoteChargeViewSet(viewsets.ModelViewSet):
    """CRUD for КП-level expense items / discounts (UBL document AllowanceCharge).

    Building the cost breakdown is a SELLER action (mirrors QuoteItemViewSet):
    only the seller team / superuser may write; the buyer never sees these rows.
    """

    serializer_class = QuoteChargeSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_fields = {"quote": ["exact"], "quote__deal_id": ["exact"]}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return QuoteCharge.objects.none()
        user = self.request.user
        from accounts.services.permissions import seller_visible_deal_ids

        queryset = QuoteCharge.objects.select_related("charge_type", "quote").all()
        if getattr(user, "is_platform_admin", False):
            return queryset
        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            from accounts.models import CompanyMember
            from accounts.services.permissions import (
                SELLER_COMPANY_TYPES,
                seller_acting_company_ids,
            )

            # The seller sees items/charges on deals routed to them. Audit H1 (no cross-seller
            # leak): hide a quote ONLY when it was prepared by a COMPETING seller company. The
            # buyer's request lines and the seller's КП are the SAME quote in this model, and
            # that quote is created by the BUYER (or left unassigned) — so scoping by
            # prepared_by's *seller* company alone wrongly hid the seller's own КП and made
            # pricing un-saveable (404 on item PATCH → subtotal stuck at 0). Exclude only
            # quotes whose prepared_by belongs to another seller company.
            seller_ids = seller_acting_company_ids(user, self.request) or set()
            # Dual-membership edge: a user who belongs to BOTH the viewer's own seller
            # company AND a competing one would otherwise land in competing_preparer_ids
            # and hide their OWN company's legitimately-prepared КП from their own viewers.
            # Subtract members of the viewer's OWN seller companies so only PURELY-competing
            # preparers are excluded.
            own_member_ids = CompanyMember.objects.filter(is_active=True, company_id__in=seller_ids).values_list(
                "user_id", flat=True
            )
            competing_preparer_ids = (
                CompanyMember.objects.filter(is_active=True, company__types__code__in=SELLER_COMPANY_TYPES)
                .exclude(company_id__in=seller_ids)
                .exclude(user_id__in=own_member_ids)
                .values_list("user_id", flat=True)
            )
            return (
                queryset.filter(quote__deal_id__in=visible_deal_ids)
                .exclude(quote__prepared_by_id__in=competing_preparer_ids)
                .distinct()
            )
        # Buyers must never see the internal cost breakdown.
        return queryset.none()

    def _assert_seller(self):
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

    def perform_create(self, serializer):
        self._assert_seller()
        quote = serializer.validated_data.get("quote")
        _assert_seller_owns_quote_deal(self.request, quote)
        # Append a manually-added charge at the BOTTOM of the cascade (after existing rows), so
        # e.g. a partner commission added last is based on the full running total above it.
        from django.db.models import Max

        next_order = (quote.charges.aggregate(m=Max("sort_order"))["m"] or 0) + 1 if quote else 0
        serializer.save(created_by=self.request.user, sort_order=next_order)

    def perform_update(self, serializer):
        self._assert_seller()
        # Editing a charge makes it the seller's deliberate value → mark it manual so a later
        # Incoterm switch (KP-05) won't wipe it with the rest of the old basis's template rows.
        serializer.save(from_template=False)

    def perform_destroy(self, instance):
        self._assert_seller()
        quote = instance.quote
        instance.delete()
        # save()-on-delete doesn't fire; recalc the КП so charges_total drops.
        quote.recalculate_totals()


@extend_schema_view(
    list=extend_schema(summary="List quote statuses", tags=["CRM"]),
)
class QuoteStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = QuoteStatus.objects.all().order_by("sort_order", "name")
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        # Lightweight {code,name} feed (no serializer_class needed) — the frontend
        # status dropdowns consume codes, not full objects.
        data = [{"code": status.code, "name": status.name} for status in self.get_queryset()]
        return Response(data)


@extend_schema_view(
    list=extend_schema(summary="List КП expense-item types (ChargeType lookup)", tags=["CRM"]),
)
class ChargeTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ChargeType.objects.filter(is_active=True).order_by("sort_order", "name")
    serializer_class = ChargeTypeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(summary="List the company's charge templates", tags=["CRM"]),
    create=extend_schema(summary="Add a charge template", tags=["CRM"]),
    destroy=extend_schema(summary="Remove a charge template", tags=["CRM"]),
)
class ChargeTemplateViewSet(viewsets.ModelViewSet):
    """Company-Admin manages their own per-Incoterm charge templates (org-admin zone).

    Scoped to the requester's seller company — they never see or touch another
    tenant's templates, nor the platform's global defaults (those are the fallback
    applied automatically when a company has no template for a basis).
    """

    serializer_class = ChargeTemplateSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def _seller_company_id(self):
        from accounts.services.permissions import primary_seller_company_id

        return primary_seller_company_id(self.request.user)

    def _assert_company_admin(self, company_id):
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import member_has_permission

        user = self.request.user
        if getattr(user, "is_superuser", False):
            return
        # Keep the explicit NO_SELLER_COMPANY signal: member_has_permission(user, None, …) is False
        # and would otherwise collapse into the generic denial below.
        if not company_id:
            raise PermissionDenied("NO_SELLER_COMPANY")
        # ADR-0005 Phase E U3: gate on the charge_templates.manage CompanyRole permission instead of
        # the legacy OWNER WorkspaceRole. A company_role-less OWNER still passes (OWNER-role fallback
        # branch); a company_role-less non-OWNER stays denied (charge_templates.manage ∈ _ADMIN_PERMS
        # → fallback False, so can_sell does not leak template management). An OWNER on a restricted
        # CompanyRole is governed by that role — intended U3 supersession.
        if not member_has_permission(user, company_id, "charge_templates.manage"):
            raise PermissionDenied("ONLY_COMPANY_ADMIN_CAN_MANAGE_TEMPLATES")

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChargeTemplate.objects.none()
        company_id = self._seller_company_id()
        if not company_id:
            return ChargeTemplate.objects.none()
        return ChargeTemplate.objects.filter(company_id=company_id).select_related("delivery_basis", "charge_type")

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        company_id = self._seller_company_id()
        self._assert_company_admin(company_id)
        basis = serializer.validated_data["delivery_basis"]
        charge_type = serializer.validated_data["charge_type"]
        if ChargeTemplate.objects.filter(company_id=company_id, delivery_basis=basis, charge_type=charge_type).exists():
            raise ValidationError({"charge_type": "TEMPLATE_ALREADY_EXISTS"})
        serializer.save(company_id=company_id)

    def perform_update(self, serializer):
        self._assert_company_admin(self._seller_company_id())
        serializer.save()

    def perform_destroy(self, instance):
        self._assert_company_admin(self._seller_company_id())
        instance.delete()
