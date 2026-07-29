from django.db.models import Prefetch
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

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


class AiDraftThrottle(UserRateThrottle):
    """Per-user throttle for the async AI draft-КП build (ARCH-01) — each call is a paid
    Claude fuzzy-match + a new Quote row. Fixed-scope throttle class (the LeadSubmitThrottle
    pattern) because ViewSet actions can't carry the view-level `throttle_scope` attribute
    the other AI endpoints use; the rate lives in DEFAULT_THROTTLE_RATES["ai_draft"]."""

    scope = "ai_draft"


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

    def get_serializer_context(self):
        # Compute the active quote's (cost-gated) unit economics ONLY on the single-deal detail —
        # the КП builder reads deal.active_quote.economics there. Off for the deals LIST so the
        # nested active_quote doesn't trigger an items+charges N+1 per row.
        ctx = super().get_serializer_context()
        ctx["include_economics"] = self.action == "retrieve"
        return ctx

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
        if getattr(user, "is_platform_admin", False):
            return queryset

        user_company_ids = list(user.memberships.filter(is_active=True).values_list("company_id", flat=True))
        buyer_scope = Q(company_id__in=user_company_ids)

        visible_deal_ids = seller_visible_deal_ids(user, self.request)
        if visible_deal_ids is not None:
            scope = Q(id__in=visible_deal_ids)
            # Opening ONE specific deal: a seller may also open a deal they own as the buyer.
            if self.action == "retrieve":
                scope |= buyer_scope
            return queryset.filter(scope)

        # Buyer / no-seller-context. LIST stays buyer-scoped (context-switching, ADR-0005), but
        # RETRIEVE of a specific deal a user is a ROUTED SELLER on must succeed regardless of the
        # active context — otherwise a seller's own company-less «калькулятор» deal (buyer=None)
        # 404s in the default BUYER context (it's a seller artifact, invisible to buyer scope).
        # force=True resolves routing regardless of the X-Active-Context header, staying
        # routing-only (no competitor widening) — the same WP-1 rule billing docs already use.
        scope = buyer_scope
        if self.action == "retrieve":
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
        without_client = str(self.request.data.get("without_client", "")).lower() in ("true", "1")

        if without_client and not contact_id:
            # Wave E F3 — «калькулятор»: a seller prices something BEFORE there is a client
            # (Deal.company NULL). Seller-only: the deal is made reachable solely by the
            # creator's DealSellerRouting row (register_new_deal → ensure_creator_seller_routing),
            # so a non-seller would create an orphan nobody — not even themselves — can see.
            # It can never be SENT until a recipient exists (RECIPIENT_REQUIRED).
            from accounts.services.permissions import is_platform_admin_viewer, primary_seller_company_id

            if is_platform_admin_viewer(user):
                raise PermissionDenied("ADMIN_VIEWER_CANNOT_ACT")
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

        # SEC (audit #7): user-initiated gate — this generic endpoint must not be a parallel
        # path around submit_request's KYC/capability gates, nor let a co-routed seller close
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
        summary="Suggested sellers for a free-text заявка (R1 — category-matched routing)",
        description=(
            "Детерминированный trigram-подбор продавцов по позициям заявки (Ariba Discovery-паттерн): "
            "каждая позиция → каталожный товар → owner_company, со счётом совпавших позиций. "
            "Чистое чтение, без AI. Покупатель подтверждает выбор через POST route/. Пустой список — "
            "каталог не подсказал, покупатель выбирает вручную."
        ),
        responses={
            200: inline_serializer(
                "SuggestedSellerItem",
                fields={
                    "company_id": drf_serializers.IntegerField(),
                    "name": drf_serializers.CharField(),
                    "matched_lines": drf_serializers.IntegerField(),
                    "total_lines": drf_serializers.IntegerField(),
                },
                many=True,
            )
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="suggested-sellers", pagination_class=None)
    def suggested_sellers(self, request, pk=None):
        """Thin wrapper (Rule 8): read-only seller suggestions for the buyer's routing step."""
        from accounts.services.permissions import is_member_of, is_platform_admin_viewer
        from sourcing.services import suggest_sellers_for_deal

        deal = self.get_object()
        if is_platform_admin_viewer(request.user):
            return Response({"detail": "ADMIN_VIEWER_CANNOT_ACT"}, status=status.HTTP_403_FORBIDDEN)
        if not is_member_of(request.user, deal.company_id, capability="buy"):
            return Response({"detail": "ONLY_BUYER_CAN_ROUTE"}, status=status.HTTP_403_FORBIDDEN)
        return Response(suggest_sellers_for_deal(deal))

    @extend_schema(
        summary="AI-enhance seller routing suggestions",
        description=(
            "R3: enqueue an AI-enhanced version of `suggested-sellers` (202 + task_id; poll "
            "sourcing/ai-status). Free-text заявка lines the trigram matcher missed are resolved "
            "in ONE bilingual LLM call so misspellings / synonyms / Latin script still route. "
            "Buyer-gated and subject to the daily AI cap; the buyer still confirms the list "
            "(AI never binds). 503 AI_DISABLED when AI is off (the sync suggested-sellers stays)."
        ),
        request=None,
        responses={
            202: OpenApiResponse(description="Enqueued — poll ai-status; result carries `sellers`"),
            403: OpenApiResponse(description="ADMIN_VIEWER_CANNOT_ACT / ONLY_BUYER_CAN_ROUTE"),
            429: OpenApiResponse(description="AI_DAILY_CAP_REACHED"),
            503: OpenApiResponse(description="AI_DISABLED"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="suggest-sellers-ai", pagination_class=None)
    def suggest_sellers_ai(self, request, pk=None):
        """Thin wrapper (Rule 8): enqueue the AI-enhanced seller suggestion for the buyer."""
        from django.conf import settings

        from accounts.services.permissions import is_member_of, is_platform_admin_viewer
        from sourcing.ai_jobs import enqueue_ai_job

        deal = self.get_object()
        if is_platform_admin_viewer(request.user):
            return Response({"detail": "ADMIN_VIEWER_CANNOT_ACT"}, status=status.HTTP_403_FORBIDDEN)
        if not is_member_of(request.user, deal.company_id, capability="buy"):
            return Response({"detail": "ONLY_BUYER_CAN_ROUTE"}, status=status.HTTP_403_FORBIDDEN)
        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return enqueue_ai_job("suggest_sellers", {"deal_id": deal.id}, request.user)

    def _assignment_response(self, deal, err, request):
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err in ("ADMIN_VIEWER_CANNOT_ACT", "MEMBER_REQUIRED_FOR_ACTION")
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": err}, status=http_status)
        # Re-fetch UNSCOPED (not via get_queryset): the service already authorized the mutation,
        # but get_queryset() is context-sensitive and excludes this deal for a delegated admin
        # (can_sell=False) or in BUYER context → would raise DoesNotExist → HTTP 500 after a
        # successful write. The service-returned object is the same deal; re-fetch only to refresh
        # prefetched caches for the serializer.
        deal = Deal.objects.get(pk=deal.pk)
        return Response(DealDetailSerializer(deal, context={"request": request}).data)

    @extend_schema(summary="Claim a deal (take it from the shared queue)", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="claim", permission_classes=[IsAuthenticated])
    def claim(self, request, pk=None):
        """ADR-0006 Move 2: a routed seller-team member takes ownership of an unclaimed заявка."""
        from crm.services.assignment import claim_deal

        deal, err = claim_deal(int(pk), request.user)
        return self._assignment_response(deal, err, request)

    @extend_schema(summary="Release a deal back to the queue", tags=["CRM"])
    @action(detail=True, methods=["post"], url_path="release", permission_classes=[IsAuthenticated])
    def release(self, request, pk=None):
        from crm.services.assignment import release_deal

        deal, err = release_deal(int(pk), request.user)
        return self._assignment_response(deal, err, request)

    @extend_schema(
        summary="Assign a deal to a team member (company admin)",
        request=inline_serializer("AssignDealRequest", fields={"assignee_id": drf_serializers.IntegerField()}),
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="assign", permission_classes=[IsAuthenticated])
    def assign(self, request, pk=None):
        from crm.services.assignment import assign_deal

        deal, err = assign_deal(int(pk), request.user, request.data.get("assignee_id"))
        return self._assignment_response(deal, err, request)

    @extend_schema(
        summary="W2 одна кнопка: взять заявку в работу и подготовить КП",
        description=(
            "One-click-quotation (утв. spec-inbound-rfq W2): claim + переход стадии в CALCULATING + "
            "предзаполненный черновик КП со строками заявки. Продавец с ai.draft получает "
            "202 {task_id, mode:'ai'} (существующий draft_quote job — AI-матч и цены, поллинг "
            "sourcing/ai-status/); без entitlement — 200 {quote_id, mode:'quote'} синхронно "
            "(копия строк + точный ГОСТ/MPN-матч + цены из своих офферов, без AI). Идемпотентно: "
            "существующий КП компании переиспользуется, повторный клик в AI-режиме возвращает "
            "уже идущий task_id (кредит не списывается дважды)."
        ),
        responses={
            200: OpenApiResponse(description="{mode:'quote', quote_id} — КП готов, открывайте билдер"),
            202: OpenApiResponse(description="{mode:'ai', task_id} — AI-черновик готовится, поллинг ai-status"),
            400: OpenApiResponse(description="Нет строк заявки / стадия вне пред-КП набора"),
            403: OpenApiResponse(description="Не routed-продавец / viewer"),
            404: OpenApiResponse(description="Deal not found"),
            409: OpenApiResponse(description="Заявку уже взял коллега (DEAL_ALREADY_CLAIMED)"),
        },
        tags=["CRM"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="take-and-prepare",
        permission_classes=[IsAuthenticated],
        throttle_classes=[AiDraftThrottle],
    )
    def take_and_prepare(self, request, pk=None):
        """Thin wrapper (Rule 8): ONE service call orchestrates claim+stage+КП; the view only
        maps error codes and, for the AI mode, enqueues the existing draft_quote job with a
        cache-backed double-click guard (an in-flight task is returned, not re-bought)."""
        from django.core.cache import cache

        from crm.services.draft_quote import take_and_prepare_quote, validate_draft_quote_gates
        from sourcing.ai_jobs import enqueue_ai_job

        result, err = take_and_prepare_quote(int(pk), request.user)
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err in ("ADMIN_VIEWER_CANNOT_ACT", "ONLY_SELLER_CAN_BUILD_QUOTE", "MEMBER_REQUIRED_FOR_ACTION")
                else status.HTTP_404_NOT_FOUND
                if err in ("DEAL_NOT_FOUND",)
                else status.HTTP_409_CONFLICT
                if err in ("DEAL_ALREADY_CLAIMED",)
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": err}, status=http_status)
        if result["mode"] == "quote":
            return Response({"mode": "quote", "quote_id": result["quote"].id, "deal_id": int(pk)})

        # AI mode. Double-click guard: while the first job is in flight its task_id is cached —
        # a second press re-polls the SAME job instead of double-spending an ai.draft credit.
        cache_key = f"draft_quote_inflight:{pk}:{request.user.id}"
        inflight_task_id = cache.get(cache_key)
        if inflight_task_id:
            return Response({"mode": "ai", "task_id": inflight_task_id}, status=status.HTTP_202_ACCEPTED)
        gate_err = validate_draft_quote_gates(int(pk), request.user)
        if gate_err:
            return Response({"detail": gate_err}, status=status.HTTP_400_BAD_REQUEST)
        response = enqueue_ai_job("draft_quote", {"deal_id": int(pk), "user_id": request.user.id}, request.user)
        if response.status_code == status.HTTP_202_ACCEPTED:
            cache.add(cache_key, response.data["task_id"], timeout=180)
            response.data["mode"] = "ai"
        return response

    @extend_schema(
        summary="Generate a pre-filled draft КП from the buyer request (AI moat / speed)",
        description=(
            "Creates a fresh DRAFT Quote for the seller, copying the buyer's request lines and "
            "prefilling matched products' cost / currency / lead-time from the seller's SupplierOffers "
            "(ADR-0006 Move 3). The seller reviews-and-sends instead of building from scratch. "
            "ARCH-01: the build (incl. the AI fuzzy match) runs on Celery — returns 202 + task_id; "
            "poll sourcing/ai-status/<task_id>/ for {prefilled, quote_id, deal}."
        ),
        responses={
            202: OpenApiResponse(description="AI draft job queued, task_id returned"),
            400: OpenApiResponse(description="No request lines"),
            403: OpenApiResponse(description="Not a routed seller / not entitled"),
            404: OpenApiResponse(description="Deal not found"),
        },
        tags=["CRM"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="generate-draft-quote",
        permission_classes=[IsAuthenticated],
        throttle_classes=[AiDraftThrottle],
    )
    def generate_draft_quote(self, request, pk=None):
        """Thin wrapper (Rule 8) — validate the cheap gates, then queue the draft-КП build."""
        from crm.services.draft_quote import validate_draft_quote_gates
        from sourcing.ai_jobs import enqueue_ai_job

        # ARCH-01: run the read-only gate checks synchronously (no LLM, no writes) so an
        # unauthorized / unentitled caller still gets an immediate 4xx instead of a queued job.
        # The worker re-runs the authoritative gates (incl. credit consumption) in the service.
        err = validate_draft_quote_gates(int(pk), request.user)
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err
                in (
                    "ADMIN_VIEWER_CANNOT_ACT",
                    "ONLY_SELLER_CAN_BUILD_QUOTE",
                    "MEMBER_REQUIRED_FOR_ACTION",
                    "AI_DRAFT_NOT_ENTITLED",
                )
                else status.HTTP_404_NOT_FOUND if err == "DEAL_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": err}, status=http_status)
        payload = {"deal_id": int(pk), "user_id": request.user.id}
        return enqueue_ai_job("draft_quote", payload, request.user)

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
        from accounts.models import Company

        sellers = Company.objects.sellers().order_by("name").values("id", "name")
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
        description="Export PDF of the deal's active quote; 202 + off-thread render when it is not ready yet.",
        responses={
            (200, "application/pdf"): OpenApiResponse(description="PDF file download"),
            202: OpenApiResponse(description="PDF rendering off-thread — retry after Retry-After seconds"),
            404: OpenApiResponse(description="No active quote"),
            409: OpenApiResponse(description="QUOTE_NOT_CLAIMED / FX_RATE_MISSING / QUOTE_BELOW_COST"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="export-pdf")
    def export_pdf(self, request, pk=None):
        """Export PDF of the deal's active quote."""
        deal = self.get_object()
        quote = deal.active_quote
        if not quote:
            return Response({"detail": "No active quote for this deal"}, status=status.HTTP_404_NOT_FOUND)
        if not quote.pdf_file:
            # ARCH-03: enqueue the off-thread render + 202 instead of running WeasyPrint
            # inline; only the cheap render guards run synchronously (409 on failure).
            from crm.services import QuoteLifecycleService
            from crm.views._pdf import pdf_generating_response

            try:
                QuoteLifecycleService.assert_pdf_renderable(quote.pk)
            except ValueError as exc:
                if str(exc) in ("QUOTE_NOT_CLAIMED", "FX_RATE_MISSING", "QUOTE_BELOW_COST"):
                    return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
                return Response({"detail": "Failed to generate PDF"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return pdf_generating_response("quote", quote.pk)
        from django.http import FileResponse

        return FileResponse(
            quote.pdf_file.open("rb"),
            content_type="application/pdf",
            as_attachment=True,
            filename=f"RailTech_Quote_{deal.id}.pdf",
        )


class DealStageLookupSerializer(drf_serializers.Serializer):
    """Response shape for the DealStage lookup feed ({code, name})."""

    code = drf_serializers.CharField()
    name = drf_serializers.CharField()


@extend_schema_view(
    list=extend_schema(summary="List deal stages", tags=["CRM"]),
)
class DealStageViewSet(viewsets.ReadOnlyModelViewSet):
    # Только активные этапы: выведенный из эксплуатации (KYC_PENDING, is_active=False) исчезает
    # из дропдауна/Канбана/воронки сам — источники этапов на фронте едины (useDealStages).
    queryset = DealStage.objects.filter(is_active=True).order_by("sort_order", "name")
    serializer_class = DealStageLookupSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        data = [{"code": s.code, "name": s.name} for s in self.get_queryset()]
        return Response(data)
