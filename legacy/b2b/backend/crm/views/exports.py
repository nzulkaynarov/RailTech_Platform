"""Focused КП export endpoint logic.

Kept out of the (already large) quotes.py ViewSet file: this is the single place
that decides the requested format, gates the seller cost/margin columns, and hands
off to crm.services.export_quote. The QuoteViewSet.export action is a thin wrapper
that calls handle_quote_export (Rule 8 — no business logic in the view).
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response

from crm.services import export_quote


def handle_quote_export(request, quote):
    """Resolve ?format=pdf|xlsx|csv and stream the rendered КП.

    - PDF is always the CLIENT projection (no cost/margin) — same rule as the
      public link / email, enforced inside the export service via quote_pdf.html.
    - XLSX/CSV may carry the seller cost & margin columns, but ONLY when the
      requester is allowed to see КП costs for THIS quote (can_view_quote_costs_for —
      own-company + permission). A buyer self-exporting gets the client-safe columns.

    `quote` is the already-permission-scoped object from the ViewSet's get_object(),
    so deal/tenant visibility is enforced before we reach here.
    """
    from accounts.services.permissions import can_view_quote_costs_for

    export_format = (request.query_params.get("format") or "pdf").lower()
    include_costs = export_format in ("xlsx", "csv") and can_view_quote_costs_for(request.user, quote)
    # MONETIZATION GATE (ADR-0006 Move 4): the SELLER's data export (xlsx/csv with cost/margin) is a
    # paid feature — gate it on quote.export. The client PDF and a buyer's client-safe export stay free
    # (never block the buyer's own document). An operational subscription grants quote.export by baseline;
    # demo/unsubscribed can't export cost data. Superuser = platform escalation, bypasses.
    if include_costs and not getattr(request.user, "is_superuser", False):
        from accounts.services import quote_export_entitled
        from accounts.services.kyc import company_kyc_verified
        from crm.services.quotes import _quote_owner_company_id

        owner_company_id = _quote_owner_company_id(quote)
        # Phase E: KYC first (distinct "do KYC" message), then the paid-export gate.
        if not company_kyc_verified(owner_company_id):
            return Response({"error": "SELLER_KYC_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
        if not quote_export_entitled(owner_company_id):
            return Response({"error": "QUOTE_EXPORT_NOT_ENTITLED"}, status=status.HTTP_403_FORBIDDEN)
    try:
        return export_quote(quote, export_format, include_costs=include_costs)
    except ValueError as exc:
        code = str(exc)
        # Loss-prevention / claim guards (HOLE 2): a КП with no FX rate, below cost, or unclaimed
        # must not render to a downloadable client document — surface the specific 409, not a 400.
        if code in ("QUOTE_NOT_CLAIMED", "FX_RATE_MISSING", "QUOTE_BELOW_COST"):
            return Response({"error": code}, status=status.HTTP_409_CONFLICT)
        return Response(
            {"error": "UNSUPPORTED_FORMAT", "supported": ["pdf", "xlsx", "csv"]},
            status=status.HTTP_400_BAD_REQUEST,
        )
