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

from crm.services import suggest_chat_reply


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
        200: OpenApiResponse(description="{'draft': str} — may be empty"),
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
            return Response({"error": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        result = suggest_chat_reply(deal_id, request.user)
        return Response(result)
