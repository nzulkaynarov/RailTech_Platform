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
    try:
        return export_quote(quote, export_format, include_costs=include_costs)
    except ValueError as exc:
        if str(exc) == "QUOTE_NOT_CLAIMED":
            return Response(
                {
                    "error": "QUOTE_NOT_CLAIMED",
                    "detail": "КП ещё не сформировано продавцом — экспорт станет доступен после отправки на согласование.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"error": "UNSUPPORTED_FORMAT", "supported": ["pdf", "xlsx", "csv"]},
            status=status.HTTP_400_BAD_REQUEST,
        )
