"""AI #4 — deal-chat reply assist endpoint.

Thin DRF wrapper (Rule 8): authorize → call ONE service → return. All the logic —
deal-visibility scoping, history fetch, the paid Claude call and the AI_IMPORT_ENABLED
gate — lives in `crm.services.suggest_chat_reply`. Mirrors `MatchCatalogView`:
IsAuthenticated, scoped throttle, neutral 503 when AI is disabled.
"""

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


@extend_schema(
    summary="AI suggest reply for a deal chat",
    description=(
        "Drafts a professional reply DRAFT for the deal's chat from its recent message "
        "history + minimal deal context. The user reviews/edits the draft before sending "
        "(human-in-loop — never auto-sent). The draft is built ONLY from the actual "
        "conversation in our DB (Rule 1: no invented commitments/prices). Returns an empty "
        "draft when the user cannot access this deal's chat, when there is no conversation "
        "yet, or when AI is off."
    ),
    responses={
        202: OpenApiResponse(
            description="AI job queued, task_id returned (poll sourcing/ai-status/<task_id>/ for {'draft': str})"
        ),
        503: OpenApiResponse(description="AI assist disabled"),
    },
    tags=["CRM"],
)
class SuggestChatReplyView(APIView):
    """AI-assisted reply draft for a deal chat (AI #4)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_chat"

    def post(self, request, deal_id):
        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # ARCH-01: deal-visibility scoping lives INSIDE the service (needs the user), so the
        # worker re-runs it with the recorded user_id — the payload carries no privileged data.
        from sourcing.ai_jobs import enqueue_ai_job

        payload = {"deal_id": deal_id, "user_id": request.user.id}
        return enqueue_ai_job("chat_reply", payload, request.user)
