"""КП approval / review chain actions for ``QuoteViewSet``, extracted as a mixin.

Split out of ``crm/views/quotes/quotes.py`` (DT3 file-length refactor) — behaviour
unchanged, purely mechanical. ``QuoteApprovalMixin`` bundles the platform-admin
force-override and the internal approval chain (submit-for-review / approval-act /
recall / my-approval-queue). Client approve / reject live in the portal (FIX-13). The
``@action`` routing (url_path / url_name / permission_classes) is identical to the
pre-split definitions, so the DRF router URLs and the OpenAPI contract are unchanged.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsPlatformAdmin
from crm.serializers import QuoteSerializer


def _chain_error_response(error):
    """Map a КП approval-chain service error code to an HTTP response."""
    forbidden = {"ROLE_NOT_PERMITTED", "SELF_APPROVAL_NOT_ALLOWED"}
    http_status = status.HTTP_403_FORBIDDEN if error in forbidden else status.HTTP_400_BAD_REQUEST
    return Response({"detail": error}, status=http_status)


class QuoteApprovalMixin:
    """КП approval-chain ``@action`` methods for ``QuoteViewSet``.

    Mixed in ahead of ``viewsets.ModelViewSet`` — it only ADDS actions and shares the
    host ViewSet's ``get_serializer`` / ``get_object`` / pagination helpers; it never
    overrides a base method, so the MRO carries no behavioural change.
    """

    # Operator sub-capability for the force-override action (ADR-0004 G1).

    @extend_schema(
        summary="Force-approve quote (Platform Admin escalation)",
        description=(
            "Bypass status guard and mark quote as APPROVED. Platform administrator only (is_superuser); "
            "a non-empty reason is mandatory. Audit-logged with [FORCE_ADMIN]."
        ),
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
        permission_classes=[IsAuthenticated, IsPlatformAdmin],
    )
    def force_approve(self, request, pk=None):
        """Platform admin force-overrides quote status to APPROVED."""
        from crm.services import QuoteLifecycleService
        from crm.views.request_body import invalid_body_response, is_object_body

        if not is_object_body(request):
            return invalid_body_response()
        reason = request.data.get("reason", "")
        quote, error = QuoteLifecycleService.force_approve_quote(int(pk), request.user, reason)
        if error:
            http_status = status.HTTP_404_NOT_FOUND if error == "QUOTE_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            return Response({"detail": error}, status=http_status)
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
        summary="Act on a КП visa step (approve / reject); the last visa sends the КП to the director in EDS",
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
            403: OpenApiResponse(
                description="ROLE_NOT_PERMITTED / SELF_APPROVAL_NOT_ALLOWED (автор КП не согласует своё КП)"
            ),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="approval-act", permission_classes=[IsAuthenticated])
    def approval_act(self, request, pk=None):
        """Проверяющий визирует или отклоняет свой шаг; последняя виза передаёт КП директору в EDS (EDS-03)."""
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
        summary="Recall a КП from approval back to DRAFT (submitter)",
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
        summary="Preview the КП approval chain (who would approve if submitted now)",
        description=(
            "Read-only Salesforce-style Approval Preview: the would-be reviewers (quote.review, names / roles). "
            "After their visas the КП goes to the director's approval route in EDS (EDS-03) — not a step here. "
            "Builds and persists NOTHING (no side effects). Seller-side only — the same quote.build gate as "
            "submit-for-review; feeds the «кто должен согласовать» preview in the send dialog."
        ),
        responses={
            200: OpenApiResponse(description="{below_floor, steps:[{...}]}"),
            403: OpenApiResponse(description="Not permitted"),
            404: OpenApiResponse(description="Quote not found"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["get"], url_path="approval-preview", permission_classes=[IsAuthenticated])
    def approval_preview(self, request, pk=None):
        """Read-only preview of the would-be approval chain (no side effects)."""
        from crm.services.approvals import preview_approval_chain

        data, error = preview_approval_chain(int(pk), request.user)
        if error:
            if error == "QUOTE_NOT_FOUND":
                return Response({"detail": error}, status=status.HTTP_404_NOT_FOUND)
            return _chain_error_response(error)
        return Response(data)

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
