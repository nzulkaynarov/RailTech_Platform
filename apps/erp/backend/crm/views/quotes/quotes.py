"""КП (`Quote`) ViewSet: CRUD, lifecycle actions (generate/send), and PDF/export.

Split out of the monolithic ``crm/views/quotes.py`` (ARCH refactor) — behaviour
unchanged. The buyer-decision (approve/reject), platform force-override and internal
approval-chain actions live in ``QuoteApprovalMixin`` (``approval.py``), which this
ViewSet mixes in (DT3 file-length split) — the ``@action`` routing is identical, so
the DRF router URLs and the OpenAPI contract are unchanged.
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
from core.permissions import ADMIN_ONLY, BUYER_ONLY, IsCompanyMemberOrPlatformAdmin, RoleGatedViewMixin
from crm import services as crm_services
from crm.constants import QuoteStatusCode
from crm.models import Quote, QuoteStatus
from crm.serializers import QuoteSerializer
from crm.views._pdf import pdf_generating_response
from crm.views.quotes.approval import QuoteApprovalMixin, _chain_error_response


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
class QuoteViewSet(RoleGatedViewMixin, QuoteApprovalMixin, OptimisticLockingMixin, viewsets.ModelViewSet):
    """
    CRUD for quotes (commercial proposals).

    Quote lifecycle: DRAFT -> SENT -> APPROVED / REJECTED.
    Includes PDF generation, send-to-client, approve, and reject actions.
    (The approve/reject/force-approve and approval-chain actions come from
    ``QuoteApprovalMixin`` — the ``operator_permissions`` map lives there too.)
    """

    # Создание и правка КП (ставка НДС, валюта, срок) — `quote.edit_pricing`: ровно то, что проверяют
    # perform_create/perform_update; остальной жизненный цикл — `quote.build`.
    required_permissions = {
        "create": "quote.edit_pricing",
        "update": "quote.edit_pricing",
        "partial_update": "quote.edit_pricing",
        "destroy": "quote.build",
        "duplicate": "quote.build",
        "generate_pdf": "quote.build",
        "recall": "quote.build",
        "set_delivery_basis": "quote.build",
        "submit_for_review": "quote.build",
        "revoke_public_link": "quote.build",
        "apply_defaults": "quote.edit_pricing",
        "charges_reorder": "quote.edit_pricing",
        "send_to_client": "quote.send",
        "approval_act": ("quote.review", "quote.approve_final"),
        "approve": BUYER_ONLY,
        "reject": BUYER_ONLY,
        "force_approve": ADMIN_ONLY,
    }
    buyer_actions = frozenset({"approve", "reject"})  # до M2-ERP-01

    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

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
        from accounts.services.permissions import sees_all_deals

        # Administrator and own-company staff (the single seller) see every КП.
        if sees_all_deals(user):
            return queryset
        # Buyer sees only quotes on their own company's deals.
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return queryset.filter(deal__company_id__in=user_company_ids)

    def perform_create(self, serializer):
        """Building a КП is a SELLER action: only own-company staff with the pricing permission
        (or superuser) may create one, and the server stamps prepared_by = the staff member building
        it (anchoring the КП-owning company + approval chain). Auto-increments version."""
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import can_edit_quote_pricing

        user = self.request.user
        if not (getattr(user, "is_superuser", False) or can_edit_quote_pricing(user)):
            raise PermissionDenied("ONLY_SELLER_CAN_BUILD_QUOTE")
        deal = serializer.validated_data.get("deal")
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
        # W2 (spec-inbound-rfq, разрыв №4): the manual «Сформировать КП» path used to create an
        # EMPTY КП — the seller re-typed lines that already exist on the заявка. Copy them here
        # (same deterministic builder as the one-click path: lines + exact GOST/MPN + own-offer
        # prices, no AI). No-op when the deal carries no request lines.
        from crm.services.draft_quote import prefill_created_quote

        prefill_created_quote(quote)

    def perform_update(self, serializer):
        """Editing КП-level settings (VAT rate, tax country, validity, currency) is a
        SELLER action — same gate as building line items / charges (can_edit_quote_pricing).
        Without this guard a buyer who can READ the КП via get_queryset could PATCH its
        pricing-relevant settings. The serializer coerces quote_currency (by code) and
        tax_country (by pk); changing vat_rate moves the VAT total, so recalc afterwards."""
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import can_edit_quote_pricing

        user = self.request.user
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
        summary="Reapply company defaults to the quote",
        description=(
            "Re-pull the seller company's CURRENT defaults (VAT rate, margin, delivery basis, "
            "validity term, cost currency) into this DRAFT КП, OVERWRITING those five fields "
            "(Odoo «Update Prices» / Salesforce «Recalculate» pattern). Seller-only, unfrozen "
            "КП only (else QUOTE_FROZEN). Returns `changed_fields` — the fields that actually "
            "differed and were updated (empty when the КП already matched the defaults)."
        ),
        request=None,
        responses={
            200: OpenApiResponse(description="Applied — `changed_fields` lists what changed"),
            403: OpenApiResponse(description="ONLY_SELLER_CAN_BUILD_QUOTE / QUOTE_FROZEN"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="apply-defaults")
    def apply_defaults(self, request, pk=None):
        """Re-pull current CompanySettings defaults into this DRAFT КП (thin wrapper — Rule 8)."""
        from rest_framework.exceptions import PermissionDenied

        from accounts.services.permissions import can_edit_quote_pricing
        from crm.services.quotes._shared import _quote_seller_company

        quote = self.get_object()
        user = request.user
        if not (getattr(user, "is_superuser", False) or can_edit_quote_pricing(user)):
            raise PermissionDenied("ONLY_SELLER_CAN_BUILD_QUOTE")
        if quote.frozen_at:
            raise PermissionDenied("QUOTE_FROZEN")
        changed = crm_services.reapply_company_defaults(quote, _quote_seller_company(quote))
        # vat_rate / margin move the КП totals — re-aggregate only when something changed.
        if changed:
            from crm.services import QuoteCalculationService

            QuoteCalculationService.recalculate_quote(quote.pk)
        return Response({"changed_fields": changed})

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
        # A FROZEN КП's file is the immutable snapshot the client received — explicit
        # regeneration is refused (staleness is impossible: frozen content never changes,
        # and re-rendering under a newer template could silently alter a legal document).
        # A frozen КП with a MISSING file (pre-existing data / lost storage) may still
        # render once via the lazy download path.
        if quote.frozen_at is not None and quote.pdf_file:
            return Response({"detail": "QUOTE_PDF_IMMUTABLE"}, status=status.HTTP_409_CONFLICT)
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
        # (Drafts self-invalidate on every content write now — recalculate_quote clears the
        # file — so this endpoint survives mainly as a manual re-render escape hatch.)
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
            "have a reachable recipient (registered client or offline contact with an email) — a "
            "company-less calculator draft has no addressee — otherwise the endpoint returns 400 "
            "RECIPIENT_REQUIRED and nothing is sent."
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
        from crm.services import QuoteLifecycleService
        from crm.services.quotes import can_send_quote_to_client

        quote = Quote.objects.select_related("status", "prepared_by", "deal").filter(pk=pk).first()
        if quote is None:
            return Response({"detail": "QUOTE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if not can_send_quote_to_client(request.user, quote):
            return _chain_error_response("ROLE_NOT_PERMITTED")
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
                    "BELOW_FLOOR_JUSTIFICATION_REQUIRED",
                    "JUSTIFICATION_TOO_LONG",
                    # Wave E F3: company-less calculator draft has no addressee yet.
                    "RECIPIENT_REQUIRED",
                )
                else "INVALID_STATUS"
            )
        return Response(self.get_serializer(quote).data)

    @extend_schema(
        summary="Duplicate a КП into a new DRAFT version (Odoo «Duplicate»)",
        description=(
            "Deep-copy this КП into a NEW DRAFT quote on the SAME deal (version = max+1): all line "
            "items (incl. sections / notes / optional lines and per-line margin), all document "
            "charges, and the КП settings. The public link, PDF, КП number and freeze/approve "
            "artefacts are NOT copied, and the FX snapshot is re-frozen at current rates on the "
            "copy's first recalc. Same seller-side authorization as building a КП (quote.build)."
        ),
        request=None,
        responses={
            201: QuoteSerializer,
            403: OpenApiResponse(description="Role not permitted (ROLE_NOT_PERMITTED)"),
            404: OpenApiResponse(description="Quote not found"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="duplicate", permission_classes=[IsAuthenticated])
    def duplicate(self, request, pk=None):
        """Deep-copy a КП into a new DRAFT (thin wrapper, Rule 8).

        Anchored to the КП-owning company like send-to-client, so it fetches the quote directly
        rather than through the deal-company-scoped get_queryset."""
        from crm.services import duplicate_quote
        from crm.services.quotes import can_duplicate_quote

        quote = Quote.objects.select_related("status", "deal").filter(pk=pk).first()
        if quote is None:
            return Response({"detail": "QUOTE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if not can_duplicate_quote(request.user, quote):
            return _chain_error_response("ROLE_NOT_PERMITTED")
        new_quote = duplicate_quote(quote.pk, request.user)
        return Response(self.get_serializer(new_quote).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Revoke the public no-login link of a sent КП",
        description="Seller pulls the shared client link (post-send panel). Idempotent; further "
        "opens return 410 QUOTE_LINK_REVOKED. Same authorization as send-to-client.",
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="revoke-public-link", permission_classes=[IsAuthenticated])
    def revoke_public_link(self, request, pk=None):
        """Revoke the КП's public link — anchored to the КП-owning company, like send-to-client."""
        from crm.services import QuoteLifecycleService
        from crm.services.quotes import can_send_quote_to_client

        quote = Quote.objects.select_related("status", "prepared_by", "deal").filter(pk=pk).first()
        if quote is None:
            return Response({"detail": "QUOTE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        if not can_send_quote_to_client(request.user, quote):
            return _chain_error_response("ROLE_NOT_PERMITTED")
        quote = QuoteLifecycleService.revoke_public_link(int(pk), request.user)
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
