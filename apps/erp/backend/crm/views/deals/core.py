"""Ядро DealViewSet: CRUD, скоупинг видимости и стадии.
Workflow-экшены — в workflow.py (распил deals.py, тех-долг)."""

from django.db import transaction
from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import ADMIN_ONLY, IsCompanyMemberOrPlatformAdmin, RoleGatedViewMixin
from crm.constants import DealStageCode
from crm.models import Deal, DealStage, Quote, QuoteItem
from crm.serializers import DealDetailSerializer, DealListSerializer
from crm.services import register_new_deal, transition_deal_stage

from .ai import DealAiActionsMixin
from .search import DealSearchFilter
from .workflow import DealWorkflowActionsMixin


@extend_schema_view(
    list=extend_schema(
        summary="List deals",
        description=(
            "Returns deals accessible to the current user. "
            "Admins/managers see all; clients see only their company's deals. "
            "`search` finds deals by number (ЗВ-ГГГГ-NNN / ПР-ГГГГ-NNN — the same NNN under either prefix, "
            "latin ZV/PR and spaces accepted), title or client company name (ERP-09)."
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
class DealViewSet(RoleGatedViewMixin, DealAiActionsMixin, DealWorkflowActionsMixin, viewsets.ModelViewSet):
    """
    CRUD for deals (the core CRM entity).

    Deal lifecycle: DRAFT -> KYC_PENDING -> SOURCING -> CALCULATING ->
    QUOTE_SENT -> CONTRACT_SIGNED -> CLOSED_WON / CLOSED_LOST.
    """

    required_permissions = {
        "create": "deal.manage",
        "update": "deal.manage",
        "partial_update": "deal.manage",
        "destroy": "deal.manage",
        "claim": "deal.manage",
        "release": "deal.manage",
        "change_stage": "deal.manage",
        "assign": "deal.assign",
        "force_change_stage": ADMIN_ONLY,
        "generate_draft_quote": "quote.edit_pricing",
        "take_and_prepare": "quote.edit_pricing",
    }

    def get_serializer_class(self):
        if self.action == "list":
            return DealListSerializer
        return DealDetailSerializer

    def get_serializer_context(self):
        # Compute the active quote's (cost-gated) unit economics ONLY on the single-deal detail —
        # the КП builder reads deal.active_quote.economics there. Off for the deals LIST so the
        # nested active_quote doesn't trigger an items+charges N+1 per row.
        ctx = super().get_serializer_context()
        ctx["include_economics"] = self.action == "retrieve"
        return ctx

    permission_classes = [IsAuthenticated, IsCompanyMemberOrPlatformAdmin]
    # Поиск по номеру ЗВ/ПР, названию и компании (ERP-09): `?search=`.
    filter_backends = [DjangoFilterBackend, DealSearchFilter]
    search_fields = ["number", "title", "company__name"]
    # Operator sub-capability for the force-override action (ADR-0004 G1).

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
            .select_related("client", "manager", "company", "stage", "assigned_to")
            .prefetch_related(Prefetch("quotes", queryset=quotes_qs))
        )

        from accounts.services.permissions import sees_all_deals

        # Продавец один — своя компания (BUSINESS §3.3): администратор и сотрудник компании-владельца
        # видят все сделки, что с ними можно делать — решают права роли в сервисах.
        if sees_all_deals(user):
            return queryset
        user_company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
        return queryset.filter(company_id__in=user_company_ids)

    def destroy(self, request, *args, **kwargs):
        """Members may delete only their own DRAFT deals; once a deal enters the
        workflow (RFQ_OPEN and beyond) it carries bids/quotes/contracts and must
        not be silently dropped — only a platform admin can remove it then
        (checkup 2026-06-10: destroy was open to any member at any stage)."""
        deal = self.get_object()
        if not request.user.is_superuser:
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
        without_client = str(self.request.data.get("without_client", "")).lower() in ("true", "1")

        if without_client and not contact_id:
            # Wave E F3 — «калькулятор»: a seller prices something BEFORE there is a client
            # (Deal.company NULL). Back-office only: a company-less deal is visible solely to the
            # own company's staff, so anyone else would create an orphan they cannot see.
            # It can never be SENT until a recipient exists (RECIPIENT_REQUIRED).
            from accounts.services.permissions import primary_seller_company_id

            if not primary_seller_company_id(user):
                raise PermissionDenied("ONLY_SELLER_CAN_CREATE_CALCULATOR_DRAFT")
            save_kwargs = dict(company=None, contact=None, client=None)
        elif contact_id:
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
            # Клиентских аккаунтов в ERP нет (FIX-13): заявку клиента создаёт портал, а в ERP
            # сделку открывает сотрудник — для калькулятора (без клиента) или из своей книги клиентов.
            raise ValidationError({"detail": "CONTACT_REQUIRED"})

        if not serializer.validated_data.get("stage"):
            draft_stage = DealStage.objects.filter(code=DealStageCode.DRAFT).first()
            if draft_stage:
                save_kwargs["stage"] = draft_stage
        with transaction.atomic():  # сделка, журнал и событие шины `request.created` (rt_bus) — одна транзакция
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

        # SEC (audit #7): user-initiated gate — this generic endpoint must not be a parallel
        # path around submit_request's capability gate; staff need the quote.build role
        # permission. (Internal auto-transitions call the service directly, ungated.)
        from crm.services.deals import assert_user_may_change_stage

        guard_error = assert_user_may_change_stage(deal, request.user, stage_code)
        if guard_error:
            return Response({"detail": guard_error}, status=status.HTTP_403_FORBIDDEN)

        deal, error = transition_deal_stage(deal, stage_code, actor=request.user)
        if error:
            return Response(
                {"detail": error},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        serializer = DealDetailSerializer(deal)
        return Response(serializer.data)

    @extend_schema(
        summary="Deal document chain (deal card hub)",
        description=(
            "Договор / счета / акты / отгрузка этой сделки одним ответом, плюс сторона зрителя "
            "и подсказка следующего шага — «карточка сделки как хаб» (паттерн smart-buttons "
            "карточки заказа Odoo). Каждый набор сужается ровно тем же правилом видимости, что "
            "и «родной» список этого типа, поэтому проигравший со-роутед продавец не увидит "
            "документов победителя. `next_step` — подсказка для UI, а не гейт: разрешения "
            "по-прежнему проверяют сервисы, выполняющие действие."
        ),
        responses={200: OpenApiResponse(description="Document chain summary")},
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="documents")
    def documents(self, request, pk=None):
        """Thin wrapper (Rule 8) — сводку собирает crm.services.deal_documents."""
        from crm.services.deal_documents import deal_document_hub

        return Response(deal_document_hub(self.get_object(), request.user, request))
