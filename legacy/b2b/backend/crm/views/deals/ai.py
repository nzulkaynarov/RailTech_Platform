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
    """AI-подбор продавцов и AI-черновик КП."""

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
