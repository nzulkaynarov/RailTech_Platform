"""Ядро DealViewSet: CRUD, скоупинг видимости, стадии и сборка заявки покупателем.
Workflow-экшены — в workflow.py (распил deals.py, тех-долг)."""

from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsCompanyMemberOrPlatformAdmin
from crm.constants import DealStageCode
from crm.models import Deal, DealStage, Quote, QuoteItem
from crm.serializers import DealDetailSerializer, DealListSerializer, QuoteItemSerializer
from crm.services import (
    buyer_add_request_item,
    buyer_add_request_items,
    buyer_update_request_meta,
    register_new_deal,
    submit_request,
    transition_deal_stage,
)

from .ai import DealAiActionsMixin
from .workflow import DealWorkflowActionsMixin

# Экшены, открывающие ОДНУ конкретную сделку (read-only). Видимость у них шире списочной:
# продавец вправе открыть сделку, где он покупатель, и наоборот. Раньше это условие было
# записано литералом `self.action == "retrieve"` в двух местах get_queryset, поэтому КАЖДЫЙ
# новый detail-экшен молча получал списочный скоуп и отдавал 404 там, где retrieve отдаёт 200.
# Набор намеренно ограничен читающими экшенами: расширять скоуп пишущим — менять границу
# безопасности.
SINGLE_DEAL_READ_ACTIONS = frozenset({"retrieve", "documents"})


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
class DealViewSet(DealAiActionsMixin, DealWorkflowActionsMixin, viewsets.ModelViewSet):
    """
    CRUD for deals (the core CRM entity).

    Deal lifecycle: DRAFT -> KYC_PENDING -> SOURCING -> CALCULATING ->
    QUOTE_SENT -> CONTRACT_SIGNED -> CLOSED_WON / CLOSED_LOST.
    """

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
        # SEC (audit #2): scope the nested quotes to the viewer's own — otherwise the
        # deal-nested `quotes`/`active_quote` (and export-pdf, which reads active_quote off
        # this prefetch) leak a competitor's full КП on a multi-seller-routed deal. Same
        # boundary QuoteViewSet enforces, via the shared helper so they can't diverge.
        from crm.services.quotes import scope_quotes_for_viewer

        quotes_qs = scope_quotes_for_viewer(quotes_qs, user, self.request)
        queryset = (
            Deal.objects.all()
            .select_related("client", "manager", "company", "stage")
            .prefetch_related(Prefetch("quotes", queryset=quotes_qs), "target_sellers")
        )

        from django.db.models import Q

        from accounts.services.permissions import seller_visible_deal_ids

        # Platform admin sees every deal (oversight). A seller acting in a seller
        # context is scoped to the RFQs ROUTED to them (multi-seller confidentiality
        # keystone — replaces the old see-all leak where seller A saw seller B's
        # buyers' заявки). A dual seller+buyer user in the BUYER context (or a pure
        # buyer) falls through to its own-company scope.
        if getattr(user, "is_superuser", False):
            return queryset

        user_company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
        buyer_scope = Q(company_id__in=user_company_ids)

        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            scope = Q(id__in=visible_deal_ids)
            # Opening ONE specific deal: a seller may also open a deal they own as the buyer.
            if self.action in SINGLE_DEAL_READ_ACTIONS:
                scope |= buyer_scope
            return queryset.filter(scope)

        # Buyer / no-seller-context. LIST stays buyer-scoped (context-switching, ADR-0005), but
        # RETRIEVE of a specific deal a user is a ROUTED SELLER on must succeed regardless of the
        # active context — otherwise a seller's own company-less «калькулятор» deal (buyer=None)
        # 404s in the default BUYER context (it's a seller artifact, invisible to buyer scope).
        # force=True resolves routing regardless of the X-Active-Context header, staying
        # routing-only (no competitor widening) — the same WP-1 rule billing docs already use.
        scope = buyer_scope
        if self.action in SINGLE_DEAL_READ_ACTIONS:
            forced = seller_visible_deal_ids(user, self.request, force=True)
            if forced:
                scope |= Q(id__in=forced)
        return queryset.filter(scope)

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
            # (Deal.company NULL). Seller-only: the deal is made reachable solely by the
            # creator's DealSellerRouting row (register_new_deal → ensure_creator_seller_routing),
            # so a non-seller would create an orphan nobody — not even themselves — can see.
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
            # Buyer-initiated deal: scoped to the user's own company.
            primary_company = user.primary_company
            if not primary_company:
                raise ValidationError(
                    {"company": _("User has no associated company. Please complete your company profile.")}
                )
            # Capability guard (server-side, not UI-only): opening a buyer RFQ is a
            # buy-side action — a member without can_buy (e.g. a seller-only member of
            # this company) must be refused here, not merely hidden in the cart UI.
            from accounts.services.permissions import is_member_of

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

        # SEC (audit #7): user-initiated gate — this generic endpoint must not be a parallel
        # path around submit_request's capability gate, nor let a co-routed seller close
        # the shared deal. (Internal auto-transitions call the service directly, ungated.)
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
