"""AI-экшены сделки (ARCH-01: обе фичи — 202 + Celery-очередь `ai`, LLM в request path нет).

Отдельный модуль: ИИ-фичи живут отдельными модулями во всём проекте (sourcing/services_ai*,
crm/services/ai_*, draft_quote) — вьюхи сделки не исключение.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle


class AiDraftThrottle(UserRateThrottle):
    """Per-user throttle for the async AI draft-КП build (ARCH-01) — each call is a paid
    Claude fuzzy-match + a new Quote row. Fixed-scope throttle class (the LeadSubmitThrottle
    pattern) because ViewSet actions can't carry the view-level `throttle_scope` attribute
    the other AI endpoints use; the rate lives in DEFAULT_THROTTLE_RATES["ai_draft"]."""

    scope = "ai_draft"


class DealAiActionsMixin:
    """AI-черновик КП."""

    @extend_schema(
        summary="Generate a pre-filled draft КП from the client request (AI moat / speed)",
        description=(
            "Creates a fresh DRAFT Quote for the seller, copying the client's request lines and "
            "prefilling matched products' cost / currency / lead-time from the seller's SupplierOffers "
            "(ADR-0006 Move 3). The seller reviews-and-sends instead of building from scratch. "
            "ARCH-01: the build (incl. the AI fuzzy match) runs on Celery — returns 202 + task_id; "
            "poll sourcing/ai-status/<task_id>/ for {prefilled, quote_id, deal}."
        ),
        responses={
            202: OpenApiResponse(description="AI draft job queued, task_id returned"),
            400: OpenApiResponse(description="No request lines"),
            403: OpenApiResponse(description="Not own-company staff"),
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
        # unauthorized caller still gets an immediate 4xx instead of a queued job.
        # The worker re-runs the authoritative gates in the service.
        err = validate_draft_quote_gates(int(pk), request.user)
        if err:
            http_status = (
                status.HTTP_403_FORBIDDEN
                if err
                in (
                    "ADMIN_VIEWER_CANNOT_ACT",
                    "ONLY_SELLER_CAN_BUILD_QUOTE",
                    "MEMBER_REQUIRED_FOR_ACTION",
                )
                else status.HTTP_404_NOT_FOUND if err == "DEAL_NOT_FOUND" else status.HTTP_400_BAD_REQUEST
            )
            return Response({"detail": err}, status=http_status)
        payload = {"deal_id": int(pk), "user_id": request.user.id}
        return enqueue_ai_job("draft_quote", payload, request.user)
