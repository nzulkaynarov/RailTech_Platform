"""AI #2 endpoint — PIM product enrichment (seller catalog assist).

Mirrors sourcing.MatchCatalogView: IsAuthenticated, ScopedRateThrottle, a hard input
cap, a 503 AI_DISABLED short-circuit when the feature is off, and a 400 on bad input.
The view is a THIN wrapper (Rule 8) — it authorizes, validates, calls ONE service
function (`catalog.ai_enrich.enrich_product`) and returns the suggestion. The seller
reviews the proposal FIELD BY FIELD in the product form and accepts or rejects each
(Akeneo AI suggestions / Shopify Magic); nothing is auto-written.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


@extend_schema(
    summary="AI enrich: draft PIM product fields (advisory)",
    description=(
        "From a product name (+ optional MPN / ГОСТ / domain) DRAFTS a description, key "
        "specifications, and PROPOSES the card's reference fields — category, unit of measure, "
        "ТН ВЭД code — plus a free-text category hint as a fallback. "
        "SUGGESTION ONLY — the seller reviews/edits before saving; nothing is auto-written. "
        "Reference fields are CHOSEN from DB-built candidate lists and verified against them "
        "server-side, never invented (Rule 1). 503 when AI is off. "
        "ARCH-01: the LLM call runs on Celery — returns 202 + task_id; poll "
        "sourcing/ai-status/<task_id>/ for {suggestion: {}}."
    ),
    request=inline_serializer(
        "ProductEnrichRequest",
        fields={
            "name": serializers.CharField(),
            "domain_code": serializers.CharField(required=False),
            "mpn": serializers.CharField(required=False),
            "gost": serializers.CharField(required=False),
        },
    ),
    responses={
        202: OpenApiResponse(description="AI job queued, task_id returned"),
        400: OpenApiResponse(description="Missing or too-long name"),
        403: OpenApiResponse(description="No catalog.manage role permission (ROLE_NOT_PERMITTED)"),
        503: OpenApiResponse(description="AI enrichment disabled"),
    },
    tags=["Catalog"],
)
class ProductEnrichView(APIView):
    """AI-assisted draft of catalog product fields for sellers (AI #2)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_enrich"

    def post(self, request):
        from django.conf import settings

        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        name = str(request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "NAME_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        # Input cap: keep the prompt bounded (mirrors the line caps on the other AI views).
        if len(name) > 255:
            return Response({"detail": "NAME_TOO_LONG"}, status=status.HTTP_400_BAD_REQUEST)

        domain_code = str(request.data.get("domain_code") or "").strip() or None
        mpn = str(request.data.get("mpn") or "").strip()[:120] or None
        gost = str(request.data.get("gost") or "").strip()[:120] or None

        # PIM enrichment is a catalog tool: gated on the catalog.manage role permission (the paid
        # ai.enrich entitlement was removed in M1-ERP-02 wave 2). Superuser always passes.
        from catalog.views.products import catalog_ai_gate

        if (gate := catalog_ai_gate(request.user)) is not None:
            return gate

        from sourcing.ai_jobs import enqueue_ai_job

        payload = {"name": name, "domain_code": domain_code, "mpn": mpn, "gost": gost}
        return enqueue_ai_job("enrich", payload, request.user)
