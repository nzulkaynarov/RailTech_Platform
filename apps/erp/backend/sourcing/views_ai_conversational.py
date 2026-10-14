"""AI #8 — conversational заявка builder endpoint.

POST a free-text description of a need → proposed structured request line items
(with REAL catalog product candidates per line). Human-in-loop: the buyer reviews,
edits and confirms the rows in the editable grid; nothing is auto-submitted.

Thin wrapper (Rule 8): authorize → validate → call ONE service → return. All the
LLM/Structured-Outputs logic lives in ``services_ai_conversational``.
"""

from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.permissions import BUYER_ONLY, RoleGatedViewMixin

# Same clamp as the service — reject obviously-oversized payloads before the LLM.
MAX_TEXT_CHARS = 4000


@extend_schema(
    summary="AI compose: free-text need → structured заявка lines (AI #8)",
    description=(
        'The buyer describes a need in plain text ("нужны подшипники 6205, '
        '4 комплекта, и перчатки рабочие 40 пар") and Claude proposes structured request '
        "line items {name, quantity, unit, mpn, gost_drawing, note} plus REAL catalog "
        "product candidates per line (ids always from a DB trigram shortlist — never "
        "invented). Human-in-loop: the buyer reviews/edits/confirms in the grid; nothing "
        "is auto-submitted. Returns {items: []} contents when AI is disabled."
    ),
    request={
        "application/json": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Free-text description of the need"},
                "domain_code": {"type": "string", "description": "Optional domain hint for catalog matching"},
            },
            "required": ["text"],
        }
    },
    responses={
        202: OpenApiResponse(
            description="AI job queued, task_id returned (poll sourcing/ai-status/<task_id>/ for {items: []})"
        ),
        400: OpenApiResponse(description="Missing/empty text"),
        503: OpenApiResponse(description="AI compose disabled"),
    },
    tags=["Sourcing"],
)
class ComposeRequestView(RoleGatedViewMixin, APIView):
    """AI #8 — turn a buyer's free-text need into reviewable заявка lines."""

    required_permissions = {
        "POST": BUYER_ONLY,
    }
    buyer_actions = frozenset({"POST"})  # до M2-ERP-01

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_compose"

    def post(self, request):
        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        text = request.data.get("text")
        if not isinstance(text, str) or not text.strip():
            return Response({"detail": "TEXT_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        domain_code = request.data.get("domain_code") or None

        # ARCH-01: TWO sequential Claude calls — the slowest interactive AI path; runs on Celery.
        from sourcing.ai_jobs import enqueue_ai_job

        payload = {"text": text[:MAX_TEXT_CHARS], "domain_code": domain_code}
        return enqueue_ai_job("compose", payload, request.user)
