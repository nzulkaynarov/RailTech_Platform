"""AI #3 — «КП vs заявка» coverage / diff endpoint.

Thin DRF wrapper (Rule 8): authorize → call ONE service → return. All logic —
the deterministic coverage check, the gated semantic AI pass and the per-quote
visibility scoping — lives in `crm.services.ai_diff`. Mirrors `MatchCatalogView`:
IsAuthenticated, scoped throttle (each call may be a paid Claude request), and a
read-only assistive result that NEVER blocks the buyer.

Both GET and POST are accepted (the check is idempotent / read-only): GET so the
buyer's КП view can fetch it on open, POST for parity with the other AI endpoints.
Scoped so only the deal's buyer or own-company staff (or the administrator)
may call it — a stranger gets 403, never another tenant's data.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from crm.models import Quote
from crm.services import user_can_view_quote_diff


@extend_schema(
    summary="AI КП-vs-заявка coverage / discrepancy check",
    description=(
        "Compares a received КП against the buyer's original request lines and returns a "
        "plain-language list of discrepancies: uncovered (unpriced) lines and — when AI is "
        "enabled — non-equivalent substitutions and notes the КП may have ignored. The "
        "deterministic coverage facts are always returned; the AI part is purely additive. "
        "Result is ASSISTIVE and never blocks. Scoped to the deal's buyer or own-company staff."
    ),
    request=None,
    responses={
        202: OpenApiResponse(
            description=(
                "AI job queued, task_id returned (poll sourcing/ai-status/<task_id>/ for "
                "{'ai_enabled': bool, 'findings': [{issue_type, line, explanation}]})"
            )
        ),
        403: OpenApiResponse(description="Caller is neither the deal's buyer nor own-company staff"),
        404: OpenApiResponse(description="Quote not found"),
    },
    tags=["CRM"],
)
class QuoteRequestDiffView(APIView):
    """AI #3 — coverage/diff of a КП vs its request (read-only, assistive)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_diff"

    def _diff(self, request, quote_id):
        try:
            quote = Quote.objects.select_related("deal").get(pk=quote_id)
        except Quote.DoesNotExist:
            return Response({"detail": "QUOTE_NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

        if not user_can_view_quote_diff(request.user, quote):
            return Response({"detail": "NOT_AUTHORIZED"}, status=status.HTTP_403_FORBIDDEN)

        # ARCH-01: the visibility 403/404 stays synchronous; the (possibly paid) diff runs on
        # Celery. user_id travels too — the worker RE-RUNS user_can_view_quote_diff so a
        # membership revoked between enqueue and execution can't still deliver the diff (TOCTOU).
        from sourcing.ai_jobs import enqueue_ai_job

        return enqueue_ai_job("quote_diff", {"quote_id": quote.id, "user_id": request.user.id}, request.user)

    def get(self, request, quote_id):
        return self._diff(request, quote_id)

    def post(self, request, quote_id):
        return self._diff(request, quote_id)
