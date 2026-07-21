"""КП approval / review chain actions for ``QuoteViewSet``, extracted as a mixin.

Split out of ``crm/views/quotes/quotes.py`` (DT3 file-length refactor) — behaviour
unchanged, purely mechanical. ``QuoteApprovalMixin`` bundles the buyer-decision
actions (approve / reject), the platform-admin force-override, and the internal
approval chain (submit-for-review / approval-act / recall / my-approval-queue). The
``@action`` routing (url_path / url_name / permission_classes) is identical to the
pre-split definitions, so the DRF router URLs and the OpenAPI contract are unchanged.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import OperatorScoped
from crm.serializers import QuoteSerializer


def _chain_error_response(error):
    """Map a КП approval-chain service error code to an HTTP response."""
    forbidden = {"ROLE_NOT_PERMITTED", "QUOTE_SEND_NOT_ENTITLED", "SELLER_KYC_REQUIRED"}
    http_status = status.HTTP_403_FORBIDDEN if error in forbidden else status.HTTP_400_BAD_REQUEST
    return Response({"detail": error}, status=http_status)


class QuoteApprovalMixin:
    """КП approval-chain + buyer-decision ``@action`` methods for ``QuoteViewSet``.

    Mixed in ahead of ``viewsets.ModelViewSet`` — it only ADDS actions and shares the
    host ViewSet's ``get_serializer`` / ``get_object`` / pagination helpers; it never
    overrides a base method, so the MRO carries no behavioural change.
    """

    # Operator sub-capability for the force-override action (ADR-0004 G1).
    operator_permissions = {"force_approve": "moderation.force_override"}

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
