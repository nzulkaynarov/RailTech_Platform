from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.services.permissions import is_seller
from core.file_streaming import stream_file_field
from core.permissions import IsCompanyMemberOrPlatformAdmin, IsPlatformAdmin
from crm import services as crm_services
from crm.models import Act, Contract, Fulfillment, Invoice, Payment, SupplierBid
from crm.serializers import (
    ActSerializer,
    ContractSerializer,
    FulfillmentSerializer,
    InvoiceSerializer,
    PaymentSerializer,
)


class Phase2StatusChoicesView(APIView):
    """Expose TextChoices-style status sets of the Phase 2 business models
    so the frontend doesn't hardcode them (IRON RULE 2).
    GET /api/v1/crm/status-choices/
    Response: {contract: [{code, label}], invoice: [...], ...}
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        def to_list(choices):
            return [{"code": c[0], "label": str(c[1])} for c in choices]

        return Response(
            {
                "contract": to_list(Contract.STATUS_CHOICES),
                "invoice": to_list(Invoice.STATUS_CHOICES),
                "act": to_list(Act.STATUS_CHOICES),
                "fulfillment": to_list(Fulfillment.STATUS_CHOICES),
                "supplier_bid": to_list(SupplierBid.STATUS_CHOICES),
                "payment_method": to_list(Payment.METHOD_CHOICES),
            }
        )


class ContractViewSet(viewsets.ModelViewSet):
    """Contracts -- generated from approved quotes, double-signed."""

    serializer_class = ContractSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Contract.objects.none()
        user = self.request.user
        qs = Contract.objects.select_related(
            "deal__company", "quote", "currency", "client_signer", "manager_signer"
        ).order_by("-created_at")
        # Seller operates across all buyer deals → sees every billing record.
        if user.is_platform_admin or is_seller(user):
            return qs
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return qs.filter(deal__company_id__in=user_company_ids)

    # Private PDFs are streamed through these authenticated endpoints (get_object
    # enforces tenant scope) — NOT via the raw /media URL, which 404s on prod
    # (local FileSystemStorage, no MinIO). See core/file_streaming.py.
    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        return stream_file_field(self.get_object().pdf_file)

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
    @action(detail=True, methods=["post"], url_path="cancel", permission_classes=[IsAuthenticated, IsPlatformAdmin])
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
        detail=True, methods=["post"], url_path="force-cancel", permission_classes=[IsAuthenticated, IsPlatformAdmin]
    )
    def force_cancel(self, request, pk=None):
        contract, err = crm_services.force_cancel_contract(
            int(pk),
            request.user,
            reason=request.data.get("reason", ""),
        )
        if err:
            return Response({"error": err}, status=400)
        return Response(ContractSerializer(contract).data)


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Invoice.objects.none()
        user = self.request.user
        qs = (
            Invoice.objects.select_related("deal__company", "contract", "currency")
            .prefetch_related(
                "items",
                "payments",
            )
            .order_by("-created_at")
        )
        # Seller operates across all buyer deals → sees every billing record.
        if user.is_platform_admin or is_seller(user):
            return qs
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return qs.filter(deal__company_id__in=user_company_ids)

    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        return stream_file_field(self.get_object().pdf_file)

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
        # Seller operates across all buyer deals → sees every billing record.
        if user.is_platform_admin or is_seller(user):
            return qs
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return qs.filter(invoice__deal__company_id__in=user_company_ids)


class ActViewSet(viewsets.ModelViewSet):
    serializer_class = ActSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Act.objects.none()
        user = self.request.user
        qs = Act.objects.select_related("deal__company", "contract", "invoice").order_by("-created_at")
        # Seller operates across all buyer deals → sees every billing record.
        if user.is_platform_admin or is_seller(user):
            return qs
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return qs.filter(deal__company_id__in=user_company_ids)

    @action(detail=True, methods=["get"], url_path="download-pdf")
    def download_pdf(self, request, pk=None):
        return stream_file_field(self.get_object().pdf_file)

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
        # Seller operates across all buyer deals → sees every billing record.
        if user.is_platform_admin or is_seller(user):
            return qs
        user_company_ids = user.memberships.filter(is_active=True).values_list("company_id", flat=True)
        return qs.filter(deal__company_id__in=user_company_ids)

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
