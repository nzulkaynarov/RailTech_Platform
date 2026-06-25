"""AI #2 endpoint — PIM product enrichment (seller catalog assist).

Mirrors sourcing.MatchCatalogView: IsAuthenticated, ScopedRateThrottle, a hard input
cap, a 503 AI_DISABLED short-circuit when the feature is off, and a 400 on bad input.
The view is a THIN wrapper (Rule 8) — it authorizes, validates, calls ONE service
function (`catalog.ai_enrich.enrich_product`) and returns the suggestion. The seller
reviews/edits the draft in the product form before saving; nothing is auto-written.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


@extend_schema(
    summary="AI enrich: draft PIM product fields (advisory)",
    description=(
        "From a product name (+ optional MPN / ГОСТ / domain) DRAFTS a description, key "
        "specifications, and a likely-category HINT string for a seller's catalog card. "
        "SUGGESTION ONLY — the seller reviews/edits before saving; nothing is auto-written. "
        "The category is a free-text hint, never a resolved id (Rule 1). 503 when AI is off."
    ),
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
            return Response({"error": "AI_DISABLED"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        name = str(request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "NAME_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)
        # Input cap: keep the prompt bounded (mirrors the line caps on the other AI views).
        if len(name) > 255:
            return Response({"error": "NAME_TOO_LONG"}, status=status.HTTP_400_BAD_REQUEST)

        domain_code = str(request.data.get("domain_code") or "").strip() or None
        mpn = str(request.data.get("mpn") or "").strip()[:120] or None
        gost = str(request.data.get("gost") or "").strip()[:120] or None

        from catalog.ai_enrich import enrich_product

        suggestion = enrich_product(name, domain_code=domain_code, mpn=mpn, gost=gost)
        return Response({"suggestion": suggestion})
