from django.db.models import Q
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import mixins
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
from crm.constants import DEFAULT_INVOICE_DUE_DAYS, InvoiceStatusCode
from crm.models import Act, Contract, Fulfillment, Invoice, InvoiceItem, Payment
from crm.serializers import (
    ActSerializer,
    ContractSerializer,
    FulfillmentSerializer,
    InvoiceSerializer,
    PaymentSerializer,
)
from crm.views.billing_filters import ActFilter, ContractFilter, FulfillmentFilter, InvoiceFilter, PaymentFilter

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


def _seller_side_q(user, request, *, deal_path, seller_path):
    """The SELLER-ownership portion of billing visibility, or None if the user owns no seller
    company. A document is on the seller side when it is OWNED by the user's seller company
    (winning quote.seller_company) OR its owner is unresolvable but the deal is routed to the
    user (legacy/manual fallback). Split out of _billing_visibility_q so DRAFT documents can be
    confined to the seller side only (I-3: a buyer must not see a seller's DRAFT invoice)."""
    owned_seller_ids = seller_company_ids(user)
    if not owned_seller_ids:
        return None
    # The seller sees documents OWNED by its seller company (winning quote.seller_company).
    owned_q = Q(**{f"{seller_path}__in": owned_seller_ids})
    # Fallback ONLY for documents whose owner is unresolvable (quote.seller_company NULL —
    # legacy/manual docs, NEVER a contracted winning quote, which is always owner-anchored on
    # claim/submit): keep them visible to a ROUTED seller by deal (WP-1). This never re-exposes a
    # winner's billing to a losing co-routed seller, because the winner's docs ARE owner-anchored.
    routed_deal_ids = seller_visible_deal_ids(user, request, force=True) or set()
    unresolved_q = Q(**{f"{seller_path}__isnull": True}) & Q(**{f"{deal_path}_id__in": routed_deal_ids})
    return owned_q | unresolved_q


def _invoice_seller_side_q(user, request):
    """SELLER-ownership Q for INVOICES, or None if the user owns no seller company.

    An invoice's owning seller is normally resolved through its contract → winning quote
    (``contract__quote__seller_company``). A G2 MANUAL invoice has NO contract, so its owner is
    resolved through its items' source КП (``items__source_quote_item__quote__seller_company``) —
    a manual DRAFT invoice raised from seller A's КП is thus OWNED by A and hidden from a co-routed
    competitor B, exactly like a contracted invoice. Subquery membership (``pk__in``) is used rather
    than a to-many join isnull so an invoice that mixes КП + ad-hoc lines resolves cleanly.

    The legacy routed-deal fallback (unresolved owner → visible to any ROUTED seller) fires ONLY
    when BOTH ownership chains are empty (a pure ad-hoc счёт with no source КП). It never re-exposes
    an owner-anchored invoice to a losing co-routed seller."""
    owned_seller_ids = seller_company_ids(user)
    if not owned_seller_ids:
        return None
    owned_via_source_ids = InvoiceItem.objects.filter(
        source_quote_item__quote__seller_company_id__in=owned_seller_ids
    ).values("invoice_id")
    any_source_owner_ids = InvoiceItem.objects.filter(source_quote_item__quote__seller_company__isnull=False).values(
        "invoice_id"
    )
    owned_q = Q(contract__quote__seller_company_id__in=owned_seller_ids) | Q(pk__in=owned_via_source_ids)
    routed_deal_ids = seller_visible_deal_ids(user, request, force=True) or set()
    unresolved_q = (
        Q(contract__quote__seller_company_id__isnull=True)
        & ~Q(pk__in=any_source_owner_ids)
        & Q(deal_id__in=routed_deal_ids)
    )
    return owned_q | unresolved_q


def _act_seller_side_q(user, request):
    """SELLER-ownership Q для АКТОВ, или None, если у пользователя нет компании-продавца.

    Владелец акта — тот же, кто владеет его счётом, поэтому цепочек резолва столько же, сколько
    у счёта: договор → КП, ЛИБО позиции счёта → исходное КП (ручной G2-счёт). Прежде путь был
    один — `invoice__contract__quote__seller_company`, — а `create_manual_invoice` создаёт счёт
    БЕЗ договора, и `generate_act` копирует этот NULL в акт. У акта по ручному счёту владелец
    не резолвился, срабатывал legacy-фолбэк «видно любому ПРОРОУТЕННОМУ продавцу», и акт
    победителя попадал в список проигравшего конкурента (тот же класс, что #463 у отгрузки:
    комментарий к фолбэку обещает «winner's docs ARE owner-anchored», а для этой модели
    обещание не выполнялось).

    Фолбэк оставлен, но срабатывает теперь только когда пусты ВСЕ цепочки — то есть у акта
    действительно нет прослеживаемого владельца.
    """
    owned_seller_ids = seller_company_ids(user)
    if not owned_seller_ids:
        return None
    owned_via_invoice_source_ids = InvoiceItem.objects.filter(
        source_quote_item__quote__seller_company_id__in=owned_seller_ids
    ).values("invoice_id")
    any_source_owner_ids = InvoiceItem.objects.filter(source_quote_item__quote__seller_company__isnull=False).values(
        "invoice_id"
    )
    owned_q = (
        Q(invoice__contract__quote__seller_company_id__in=owned_seller_ids)
        | Q(contract__quote__seller_company_id__in=owned_seller_ids)
        | Q(invoice_id__in=owned_via_invoice_source_ids)
    )
    routed_deal_ids = seller_visible_deal_ids(user, request, force=True) or set()
    unresolved_q = (
        Q(invoice__contract__quote__seller_company_id__isnull=True)
        & Q(contract__quote__seller_company_id__isnull=True)
        & ~Q(invoice_id__in=any_source_owner_ids)
        & Q(deal_id__in=routed_deal_ids)
    )
    return owned_q | unresolved_q


def act_visibility_q(user, request):
    """Полная Q видимости АКТОВ для не-админа: покупательская сторона ∪ владеющий продавец."""
    user_company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    buyer_q = Q(deal__company_id__in=user_company_ids)
    seller_q = _act_seller_side_q(user, request)
    return buyer_q if seller_q is None else (buyer_q | seller_q)


def invoice_visibility_q(user, request):
    """Полная Q видимости СЧЕТОВ для не-админа: чья это сторона + запрет чужого черновика.

    Вынесено из `InvoiceViewSet.get_queryset`, потому что у счёта видимость сложнее прочих
    (владелец резолвится через договор ИЛИ через исходное КП позиций ручного счёта) и её
    понадобилось переиспользовать в сводке документов сделки. Копия этой логики стала бы
    вторым определением видимости — тем самым классом расхождения, из-за которого отгрузка
    победителя утекала проигравшему (#463).
    """
    user_company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
    buyer_q = Q(deal__company_id__in=user_company_ids)
    seller_side_q = _invoice_seller_side_q(user, request)
    visibility_q = buyer_q if seller_side_q is None else (buyer_q | seller_side_q)
    # I-3: a DRAFT invoice is the seller's private working copy — hidden from the buyer until
    # it is ISSUED (Odoo canon: a draft is not shown to the customer). CANCELLED/ISSUED/… stay
    # visible to both sides. seller_side_q ⊆ visibility_q, so ANDing the gate keeps non-DRAFT
    # rows untouched and confines DRAFT rows to the seller side. A pure buyer (no seller
    # company) has seller_side_q=None → never matches a DRAFT.
    draft_gate = ~Q(status__code=InvoiceStatusCode.DRAFT)
    if seller_side_q is not None:
        draft_gate = draft_gate | seller_side_q
    return visibility_q & draft_gate


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
    seller_q = _seller_side_q(user, request, deal_path=deal_path, seller_path=seller_path)
    if seller_q is None:
        return buyer_q
    return buyer_q | seller_q


class ContractViewSet(OptimisticLockingMixin, viewsets.ModelViewSet):
    """Contracts -- generated from approved quotes, double-signed."""

    serializer_class = ContractSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    # Без FilterSet DjangoFilterBackend молча возвращает список ЦЕЛИКОМ — см. billing_filters.
    filterset_class = ContractFilter
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

    @extend_schema(
        summary="Select an approved wording variant for THIS contract (E4 playbook)",
        tags=["CRM"],
        request=inline_serializer(
            "SelectContractWording",
            fields={
                "field": drf_serializers.CharField(),
                "variant_id": drf_serializers.IntegerField(required=False, allow_null=True),
            },
        ),
    )
    @action(detail=True, methods=["post"], url_path="select-wording")
    def select_wording(self, request, pk=None):
        from crm.services.wording_variants import select_contract_wording

        contract = self.get_object()
        contract, err = select_contract_wording(
            contract,
            request.user,
            field=str(request.data.get("field", "")),
            variant_id=request.data.get("variant_id"),
        )
        if err:
            return Response({"detail": err}, status=400)
        return Response(ContractSerializer(contract).data)

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


class InvoiceViewSet(
    OptimisticLockingMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Счета. Сырые `create`/`destroy` НЕ подключены намеренно (Rule 8).

    Выставление счёта — только через сервисные экшены `create-manual` и
    `generate-from-contract`; отмена — через `cancel` (сервис `cancel_invoice`).
    Сырое удаление обходило бы отмену, а при наличии платежей падало бы в
    `ProtectedError` → 500 (`Payment.invoice` объявлен с `on_delete=PROTECT`).
    `update` оставлен: им правят черновик (due_date / notes), и он уже загейчен
    на DRAFT ниже — фронтенд использует именно его.
    """

    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_class = InvoiceFilter

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
        # Invoice ownership resolves through the contract chain OR — for a G2 contract-less MANUAL
        # invoice — through its items' source КП. Buyer sees its deals' invoices; seller sees the
        # ones its company OWNS (hidden competition). Shared with the deal-documents hub.
        return qs.filter(invoice_visibility_q(user, self.request)).distinct()

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
            request.user,
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

    @extend_schema(
        summary="Create a manual DRAFT invoice (no signed contract)",
        description=(
            "Raise a DRAFT invoice directly on a deal WITHOUT a signed contract (Odoo / МойСклад "
            "«invoice without contract»; СНГ «счёт = оферта»). Populate lines from an active КП on "
            "the deal (`source_quote` → same billable projection as the contract path) and/or a "
            "manual line list. Amounts follow the КП presentation currency (UZS), never a cost "
            "currency. The invoice is born DRAFT and rides the existing issue / cancel lifecycle."
        ),
        request=inline_serializer(
            "CreateManualInvoice",
            fields={
                "deal": drf_serializers.IntegerField(),
                "source_quote": drf_serializers.IntegerField(required=False),
                "due_days": drf_serializers.IntegerField(required=False, default=DEFAULT_INVOICE_DUE_DAYS),
                "lines": drf_serializers.ListField(
                    required=False,
                    child=inline_serializer(
                        "ManualInvoiceLine",
                        fields={
                            "description": drf_serializers.CharField(),
                            "quantity": drf_serializers.IntegerField(),
                            "unit_price_excl_vat": drf_serializers.DecimalField(max_digits=14, decimal_places=2),
                        },
                    ),
                ),
            },
        ),
        responses={201: InvoiceSerializer, 400: OpenApiResponse(description="Validation / authorization error")},
        tags=["CRM"],
    )
    @action(detail=False, methods=["post"], url_path="create-manual", permission_classes=[IsAuthenticated])
    def create_manual(self, request):
        deal_id = request.data.get("deal")
        if not deal_id:
            return Response({"detail": "DEAL_ID_REQUIRED"}, status=400)
        source_quote = request.data.get("source_quote")
        invoice, err = crm_services.create_manual_invoice(
            int(deal_id),
            actor=request.user,
            source_quote_id=int(source_quote) if source_quote else None,
            lines=request.data.get("lines"),
            due_days=int(request.data.get("due_days", DEFAULT_INVOICE_DUE_DAYS)),
        )
        if err:
            forbidden = {"ADMIN_VIEWER_CANNOT_ACT", "MEMBER_REQUIRED_FOR_ACTION"}
            http_status = 404 if err == "NOT_FOUND" else (403 if err in forbidden else 400)
            return Response({"detail": err}, status=http_status)
        return Response(InvoiceSerializer(invoice, context=self.get_serializer_context()).data, status=201)

    @extend_schema(summary="Generate invoice from a signed contract", tags=["CRM"])
    @action(
        detail=False,
        methods=["post"],
        url_path="generate-from-contract",
        permission_classes=[IsAuthenticated],
    )
    def generate_from_contract(self, request):
        contract_id = request.data.get("contract_id")
        due_days = int(request.data.get("due_days", DEFAULT_INVOICE_DUE_DAYS))
        if not contract_id:
            return Response({"detail": "CONTRACT_ID_REQUIRED"}, status=400)
        invoice, err = crm_services.generate_invoice_from_contract(
            int(contract_id),
            actor=request.user,
            due_days=due_days,
        )
        if err:
            return Response({"detail": err}, status=(404 if err == "NOT_FOUND" else 400))
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
            return Response({"detail": err}, status=(404 if err == "NOT_FOUND" else 400))
        return Response(PaymentSerializer(payment).data, status=201)

    @extend_schema(summary="Generate Act for this invoice", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="generate-act", permission_classes=[IsAuthenticated])
    def generate_act(self, request, pk=None):
        act, err = crm_services.generate_act(int(pk), actor=request.user)
        if err:
            return Response({"detail": err}, status=(404 if err == "NOT_FOUND" else 400))
        return Response(ActSerializer(act).data, status=201)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """Платежи — ТОЛЬКО чтение (Rule 8).

    Запись идёт исключительно через `invoices/{id}/record-payment/` → сервис
    `record_payment`, который проверяет права покупателя, статус счёта и
    положительность суммы, пересчитывает `amount_paid`/статус и пишет в аудит.
    Сырой `POST /crm/payments/` всё это обходил: любой аутентифицированный
    пользователь мог вписать в реестр строку (в т.ч. отрицательную) по ЧУЖОМУ
    счёту, а `amount_paid` счёта при этом не менялся — реестр расходился со счётом.
    """

    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_class = PaymentFilter

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


class ActViewSet(viewsets.ReadOnlyModelViewSet):
    """Акты — только чтение плюс сервисные экшены ниже (Rule 8).

    Выпуск — через `invoices/{id}/generate-act/` (там же проверяется роутинг
    продавца, аудит H4), подпись — через `acts/{id}/sign/`. Сырые create/update/
    destroy обходили обе проверки и позволяли проставить номер, статус и даты руками.
    """

    serializer_class = ActSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_class = ActFilter

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Act.objects.none()
        user = self.request.user
        qs = Act.objects.select_related("deal__company", "contract", "invoice", "status").order_by("-created_at")
        # Platform admin sees every billing record; otherwise BOTH sides of a deal
        # (buyer company + routed seller) see its records, regardless of the SPA
        # X-Active-Context header (WP-1). Владелец акта резолвится по всем цепочкам его
        # счёта — иначе акт по ручному счёту уходил в фолбэк и был виден конкуренту.
        if getattr(user, "is_platform_admin", False):
            return qs
        return qs.filter(act_visibility_q(user, self.request)).distinct()

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

        # `self.get_object()` — а не `int(pk)`: только внутри него DRF применяет
        # `check_object_permissions` и сужение `get_queryset()`. С сырым pk экшен обходил обе
        # защиты, а `sign_act` проверял лишь оператора-наблюдателя — посторонний пользователь
        # подписывал ЧУЖОЙ акт по прямому id и получал HTTP 200. Соседние экшены акта
        # (download-pdf, download-signed) уже шли через get_object.
        act, err = crm_services.sign_act(self.get_object().id, request.user, signed_file=signed_file)
        if err:
            return Response({"detail": err}, status=400)
        return Response(ActSerializer(act, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Reject an issued act (buyer side)",
        description=(
            "Заказчик возвращает акт исполнителю с причиной — второй шаг двустороннего цикла "
            "(паттерн ЭСФ «подтвердить или отклонить»). Причина обязательна: без основания "
            "отказ бесполезен обеим сторонам. Акт уходит обратно в DRAFT."
        ),
        request=inline_serializer("RejectAct", fields={"reason": drf_serializers.CharField()}),
        responses={200: ActSerializer, 400: OpenApiResponse(description="REASON_REQUIRED / ACT_SIGN_NOT_ALLOWED")},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        act, err = crm_services.reject_act(self.get_object().id, request.user, reason=request.data.get("reason", ""))
        if err:
            return Response({"detail": err}, status=400)
        return Response(ActSerializer(act, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Remind the customer that the act awaits acceptance (issuer side)",
        description=(
            "Исполнитель повторно приглашает заказчика ответить по выставленному акту. Уходит "
            "ТО ЖЕ письмо «акт ждёт подтверждения», а не новый его вид — число писем на отрезке "
            "не растёт (аналог Resend у DocuSign). Не чаще раза в сутки на документ: ограничение "
            "взято у PandaDoc, иначе кнопка становится инструментом спама."
        ),
        request=None,
        responses={
            200: ActSerializer,
            400: OpenApiResponse(description="ACT_REMINDER_TOO_SOON / ACT_ISSUER_SIDE_REQUIRED"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="remind")
    def remind(self, request, pk=None):
        act, err = crm_services.remind_act_acceptance(self.get_object().id, request.user)
        if err:
            return Response({"detail": err}, status=400)
        return Response(ActSerializer(act, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Cancel (void) an act — issuer side only",
        description=(
            "Выпустившая сторона отзывает собственный акт. Причина обязательна и уходит "
            "заказчику вместе с уведомлением (так же устроены void у DocuSign и cancel у Adobe "
            "Acrobat Sign). Статус терминальный: согласованный обеими сторонами акт не "
            "отзывается — его судьбу решает новый акт."
        ),
        request=inline_serializer("CancelAct", fields={"reason": drf_serializers.CharField()}),
        responses={
            200: ActSerializer,
            400: OpenApiResponse(description="REASON_REQUIRED / ACT_CANCEL_NOT_ALLOWED / ACT_ISSUER_SIDE_REQUIRED"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        act, err = crm_services.cancel_act(self.get_object().id, request.user, reason=request.data.get("reason", ""))
        if err:
            return Response({"detail": err}, status=400)
        return Response(ActSerializer(act, context=self.get_serializer_context()).data)


class FulfillmentViewSet(viewsets.ReadOnlyModelViewSet):
    """Отгрузки — только чтение плюс экшен `update-status` (Rule 8).

    Сырой CRUD позволял, среди прочего, проставить или сбросить `contract` —
    привязку к владельцу, от которой зависит видимость записи для продавца.
    """

    serializer_class = FulfillmentSerializer
    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    filterset_class = FulfillmentFilter

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
