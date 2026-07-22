from django.db.models import Q
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.services.permissions import seller_company_ids, seller_visible_deal_ids
from core.file_streaming import stream_file_field
from core.optimistic_locking import OptimisticLockingMixin
from core.permissions import IsCompanyMemberOrPlatformAdmin, OperatorScoped
from crm import services as crm_services
from crm.models import (
    Act,
    Contract,
    Fulfillment,
    Invoice,
    Payment,
)
from crm.serializers import (
    ActSerializer,
    ContractSerializer,
    FulfillmentSerializer,
    InvoiceSerializer,
    PaymentSerializer,
)

_PDF_DOC_TYPE = {"Contract": "contract", "Invoice": "invoice", "Act": "act"}


def _stream_or_render_pdf(obj):
    """Stream a document's PDF, or 202 + enqueue the off-thread render (ARCH-03).

    Creation schedules the render asynchronously (F1.6), so a download can race ahead
    of the Celery task — or arrive while the worker is down. WeasyPrint never runs
    inline in the request thread: the idempotent render task is (re-)enqueued and the
    caller polls with the Retry-After hint (lib/download.ts in the SPA)."""
    if not obj.pdf_file:
        from crm.views._pdf import pdf_generating_response

        return pdf_generating_response(_PDF_DOC_TYPE[type(obj).__name__], obj.id)
    return stream_file_field(obj.pdf_file)


def _billing_visibility_q(user, request, *, deal_path, seller_path):
    """Tenant-scope Q for a non-admin billing queryset.

    A billing document (contract / invoice / act / payment / fulfillment) is visible to:
      • a member of the BUYER company that owns the deal (deal_path → company), UNION
      • a member of the SELLER company that OWNS the document — the winning quote's
        seller_company (seller_path → quote.seller_company).

    Scoping the seller side to the document's OWN seller_company — not to every deal the
    seller is merely ROUTED to — is what stops a LOSING co-routed seller from seeing the
    WINNER's contract/invoice/act/payment on a shared multi-seller deal (hidden competition,
    ADR-0003 §5). Billing models carry no seller_company field, so ownership is derived through
    the quote chain. Visibility is INDEPENDENT of the SPA X-Active-Context header — a seller
    landing in the default BUYER context still sees its own deals' billing (WP-1).

    `deal_path`   — ORM prefix from the model to its Deal FK ("deal", or "invoice__deal" for Payment).
    `seller_path` — ORM prefix from the model to the owning quote's seller_company id.
    """
    user_company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    buyer_q = Q(**{f"{deal_path}__company_id__in": user_company_ids})
    owned_seller_ids = seller_company_ids(user)
    if not owned_seller_ids:
        return buyer_q
    # The seller sees documents OWNED by its seller company (winning quote.seller_company).
    owned_q = Q(**{f"{seller_path}__in": owned_seller_ids})
    # Fallback ONLY for documents whose owner is unresolvable (quote.seller_company NULL —
    # legacy/manual docs, NEVER a contracted winning quote, which is always owner-anchored on
    # claim/submit): keep them visible to a ROUTED seller by deal (WP-1). This never re-exposes a
    # winner's billing to a losing co-routed seller, because the winner's docs ARE owner-anchored.
    routed_deal_ids = seller_visible_deal_ids(user, request, force=True) or set()
    unresolved_q = Q(**{f"{seller_path}__isnull": True}) & Q(**{f"{deal_path}_id__in": routed_deal_ids})
    return buyer_q | owned_q | unresolved_q


class ContractViewSet(OptimisticLockingMixin, viewsets.ModelViewSet):
    """Contracts -- generated from approved quotes, double-signed."""

    serializer_class = ContractSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    # Operator sub-capability for the admin contract overrides (ADR-0004 G1).
    operator_permissions = {
        "cancel": "moderation.force_override",
        "force_cancel": "moderation.force_override",
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Contract.objects.none()
        user = self.request.user
        qs = Contract.objects.select_related(
            "deal__company", "quote", "currency", "client_signer", "manager_signer", "status"
        ).order_by("-created_at")
        # Platform admin sees every billing record; otherwise BOTH sides of a deal
        # (buyer company + routed seller) see its records, regardless of the SPA
        # X-Active-Context header (WP-1). Seller side stays routing-scoped.
        if getattr(user, "is_platform_admin", False):
            return qs
        return qs.filter(
            _billing_visibility_q(user, self.request, deal_path="deal", seller_path="quote__seller_company_id")
        ).distinct()

    # Private PDFs are streamed through these authenticated endpoints (get_object
    # enforces tenant scope) — NOT via the raw /media URL, which 404s on prod
    # (local FileSystemStorage, no MinIO). See core/file_streaming.py.
    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        return _stream_or_render_pdf(self.get_object())

    @action(detail=True, methods=["get"], url_path="download-signed")
    def download_signed(self, request, pk=None):
        return stream_file_field(self.get_object().signed_file)

    @extend_schema(
        summary="Generate contract from a quote",
        tags=["CRM"],
        request=inline_serializer(
            "GenContract",
            fields={
                "quote_id": drf_serializers.IntegerField(),
                "notes": drf_serializers.CharField(required=False, default=""),
            },
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="generate-from-quote",
        permission_classes=[IsAuthenticated],
    )
    def generate_from_quote(self, request):
        quote_id = request.data.get("quote_id")
        if not quote_id:
            return Response({"detail": "QUOTE_ID_REQUIRED"}, status=400)
        contract, err = crm_services.generate_contract_from_quote(
            int(quote_id),
            actor=request.user,
            notes=request.data.get("notes", ""),
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(ContractSerializer(contract).data, status=201)

    @extend_schema(summary="Sign contract by client", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="sign-client")
    def sign_client(self, request, pk=None):
        contract, err = crm_services.sign_contract_by_client(int(pk), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(ContractSerializer(contract).data)

    @extend_schema(summary="Sign contract by manager (RailTech side)", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="sign-manager", permission_classes=[IsAuthenticated])
    def sign_manager(self, request, pk=None):
        contract, err = crm_services.sign_contract_by_manager(int(pk), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(ContractSerializer(contract).data)

    @extend_schema(summary="Upload signed copy", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="upload-signed", parser_classes=[MultiPartParser, FormParser])
    def upload_signed(self, request, pk=None):
        contract = self.get_object()
        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"detail": "NO_FILE_PROVIDED"}, status=400)

        from django.core.exceptions import ValidationError

        from core.validators import validate_document_upload

        try:
            validate_document_upload(file_obj)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        contract.signed_file = file_obj
        contract.save(update_fields=["signed_file", "updated_at"])
        return Response(ContractSerializer(contract).data)

    @extend_schema(summary="Cancel contract", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="cancel", permission_classes=[IsAuthenticated, OperatorScoped])
    def cancel(self, request, pk=None):
        contract, err = crm_services.cancel_contract(int(pk), request.user, reason=request.data.get("reason", ""))
        if err:
            return Response({"detail": err}, status=400)
        return Response(ContractSerializer(contract).data)

    @extend_schema(
        summary="Force-cancel contract (Platform Admin escalation)",
        description="Bypass SIGNED guard and mark contract CANCELLED. ADMIN role required. Audit-logged with [FORCE_ADMIN].",
        request=inline_serializer(
            "ForceCancelContractRequest",
            fields={
                "reason": drf_serializers.CharField(required=True),
            },
        ),
        responses={200: ContractSerializer, 400: OpenApiResponse(description="Validation error")},
        tags=["CRM"],
    )
    @action(
        detail=True, methods=["post"], url_path="force-cancel", permission_classes=[IsAuthenticated, OperatorScoped]
    )
    def force_cancel(self, request, pk=None):
        contract, err = crm_services.force_cancel_contract(
            int(pk),
            request.user,
            reason=request.data.get("reason", ""),
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(ContractSerializer(contract).data)


class InvoiceViewSet(OptimisticLockingMixin, viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Invoice.objects.none()
        user = self.request.user
        qs = (
            Invoice.objects.select_related("deal__company", "contract", "currency", "status")
            .prefetch_related(
                "items",
                "payments",
            )
            .order_by("-created_at")
        )
        # Platform admin sees every billing record; otherwise BOTH sides of a deal
        # (buyer company + routed seller) see its records, regardless of the SPA
        # X-Active-Context header (WP-1). Seller side stays routing-scoped.
        if getattr(user, "is_platform_admin", False):
            return qs
        return qs.filter(
            _billing_visibility_q(
                user, self.request, deal_path="deal", seller_path="contract__quote__seller_company_id"
            )
        ).distinct()

    def update(self, request, *args, **kwargs):
        """DRAFT-only edit, restricted to due_date / notes (amounts mirror the contract, never
        hand-edited). Covers PATCH too (DRF routes partial_update → update). ISSUED+ are immutable
        → 400 INVOICE_NOT_EDITABLE. Honours the optimistic-lock If-Match token like the base mixin."""
        from crm.constants import InvoiceStatusCode

        invoice = self.get_object()
        if invoice.status_code != InvoiceStatusCode.DRAFT:
            return Response({"detail": "INVOICE_NOT_EDITABLE"}, status=400)
        if_match = request.headers.get("If-Match")
        if if_match and if_match != self._etag_for(invoice):
            return Response({"detail": "PRECONDITION_FAILED_STALE_WRITE"}, status=status.HTTP_412_PRECONDITION_FAILED)
        updated, err = crm_services.update_invoice_draft(
            invoice,
            due_date=request.data.get("due_date"),
            notes=request.data.get("notes"),
        )
        if err:
            return Response({"detail": err}, status=400)
        response = Response(InvoiceSerializer(updated, context=self.get_serializer_context()).data)
        response["ETag"] = self._etag_for(updated)
        return response

    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        return _stream_or_render_pdf(self.get_object())

    @extend_schema(summary="Issue a DRAFT invoice (DRAFT → ISSUED)", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="issue", permission_classes=[IsAuthenticated])
    def issue(self, request, pk=None):
        invoice, err = crm_services.issue_invoice(self.get_object(), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(InvoiceSerializer(invoice, context=self.get_serializer_context()).data)

    @extend_schema(summary="Cancel an invoice (→ CANCELLED; not allowed if paid)", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="cancel", permission_classes=[IsAuthenticated])
    def cancel(self, request, pk=None):
        invoice, err = crm_services.cancel_invoice(self.get_object(), request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(InvoiceSerializer(invoice, context=self.get_serializer_context()).data)

    @extend_schema(summary="Generate invoice from a signed contract", tags=["CRM"])
    @action(
        detail=False,
        methods=["post"],
        url_path="generate-from-contract",
        permission_classes=[IsAuthenticated],
    )
    def generate_from_contract(self, request):
        contract_id = request.data.get("contract_id")
        due_days = int(request.data.get("due_days", 14))
        if not contract_id:
            return Response({"detail": "CONTRACT_ID_REQUIRED"}, status=400)
        invoice, err = crm_services.generate_invoice_from_contract(
            int(contract_id),
            actor=request.user,
            due_days=due_days,
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(InvoiceSerializer(invoice).data, status=201)

    @extend_schema(
        summary="Record a payment against this invoice",
        tags=["CRM"],
        request=inline_serializer(
            "RecordPayment",
            fields={
                "amount": drf_serializers.DecimalField(max_digits=14, decimal_places=2),
                "paid_at": drf_serializers.DateField(),
                "method": drf_serializers.CharField(required=False, default="BANK_TRANSFER"),
                "reference": drf_serializers.CharField(required=False, default=""),
            },
        ),
    )
    @action(detail=True, methods=["post"], url_path="record-payment", permission_classes=[IsAuthenticated])
    def record_payment(self, request, pk=None):
        payment, err = crm_services.record_payment(
            int(pk),
            actor=request.user,
            amount=request.data.get("amount"),
            paid_at=request.data.get("paid_at"),
            method=request.data.get("method", "BANK_TRANSFER"),
            reference=request.data.get("reference", ""),
            proof_file=request.FILES.get("proof_file"),
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(PaymentSerializer(payment).data, status=201)

    @extend_schema(summary="Generate Act for this invoice", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="generate-act", permission_classes=[IsAuthenticated])
    def generate_act(self, request, pk=None):
        act, err = crm_services.generate_act(int(pk), actor=request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(ActSerializer(act).data, status=201)


class PaymentViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        user = self.request.user
        qs = Payment.objects.select_related("invoice__deal__company").order_by("-paid_at")
        # Platform admin sees every billing record; otherwise BOTH sides of a deal
        # (buyer company + routed seller) see its records, regardless of the SPA
        # X-Active-Context header (WP-1). Payment reaches its deal via invoice__deal.
        if getattr(user, "is_platform_admin", False):
            return qs
        return qs.filter(
            _billing_visibility_q(
                user,
                self.request,
                deal_path="invoice__deal",
                seller_path="invoice__contract__quote__seller_company_id",
            )
        ).distinct()


class ActViewSet(viewsets.ModelViewSet):
    serializer_class = ActSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Act.objects.none()
        user = self.request.user
        qs = Act.objects.select_related("deal__company", "contract", "invoice", "status").order_by("-created_at")
        # Platform admin sees every billing record; otherwise BOTH sides of a deal
        # (buyer company + routed seller) see its records, regardless of the SPA
        # X-Active-Context header (WP-1). Seller side stays routing-scoped.
        if getattr(user, "is_platform_admin", False):
            return qs
        return qs.filter(
            _billing_visibility_q(
                user, self.request, deal_path="deal", seller_path="invoice__contract__quote__seller_company_id"
            )
        ).distinct()

    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        return _stream_or_render_pdf(self.get_object())

    @action(detail=True, methods=["get"], url_path="download-signed")
    def download_signed(self, request, pk=None):
        return stream_file_field(self.get_object().signed_file)

    @extend_schema(summary="Sign act (mark as SIGNED)", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="sign", parser_classes=[MultiPartParser, FormParser])
    def sign(self, request, pk=None):
        signed_file = request.FILES.get("signed_file")
        if signed_file:
            from django.core.exceptions import ValidationError

            from core.validators import validate_document_upload

            try:
                validate_document_upload(signed_file)
            except ValidationError as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        act, err = crm_services.sign_act(int(pk), request.user, signed_file=signed_file)
        if err:
            return Response({"detail": err}, status=400)
        return Response(ActSerializer(act).data)


class FulfillmentViewSet(viewsets.ModelViewSet):
    serializer_class = FulfillmentSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Fulfillment.objects.none()
        user = self.request.user
        qs = Fulfillment.objects.select_related("deal__company").order_by("-updated_at")
        # Platform admin sees every billing record; otherwise BOTH sides of a deal
        # (buyer company + routed seller) see its records, regardless of the SPA
        # X-Active-Context header (WP-1). Seller side stays routing-scoped.
        if getattr(user, "is_platform_admin", False):
            return qs
        return qs.filter(
            _billing_visibility_q(
                user, self.request, deal_path="deal", seller_path="contract__quote__seller_company_id"
            )
        ).distinct()

    @extend_schema(summary="Update fulfillment status", tags=["CRM"])
    @action(detail=False, methods=["post"], url_path="update-status", permission_classes=[IsAuthenticated])
    def update_status(self, request):
        deal_id = request.data.get("deal_id")
        status_code = request.data.get("status")
        if not deal_id or not status_code:
            return Response({"detail": "DEAL_ID_AND_STATUS_REQUIRED"}, status=400)
        extra = {k: request.data.get(k) for k in ("tracking_number", "carrier", "expected_delivery_date", "notes")}
        obj, err = crm_services.update_fulfillment_status(
            int(deal_id),
            request.user,
            status_code,
            **extra,
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(FulfillmentSerializer(obj).data)
