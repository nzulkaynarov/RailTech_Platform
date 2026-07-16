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
    """Resolve ?export_format=pdf|xlsx|csv and stream the rendered КП.

    - PDF is always the CLIENT projection (no cost/margin) — same rule as the
      public link / email, enforced inside the export service via quote_pdf.html.
    - XLSX/CSV may carry the seller cost & margin columns, but ONLY when the
      requester is allowed to see КП costs for THIS quote (can_view_quote_costs_for —
      own-company + permission). A buyer self-exporting gets the client-safe columns.

    `quote` is the already-permission-scoped object from the ViewSet's get_object(),
    so deal/tenant visibility is enforced before we reach here.
    """
    from accounts.services.permissions import can_view_quote_costs_for

    # NOTE: the query key is `export_format`, NOT `format`. DRF's URL_FORMAT_OVERRIDE
    # ('format') hijacks `?format=pdf` during content-negotiation and raises Http404
    # (no renderer for format='pdf') BEFORE this view runs — so `?format=…` 404s the
    # whole export. `export_format` sidesteps DRF's reserved parameter entirely.
    export_format = (request.query_params.get("export_format") or "pdf").lower()
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
            return Response({"detail": "SELLER_KYC_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)
        if not quote_export_entitled(owner_company_id):
            return Response({"detail": "QUOTE_EXPORT_NOT_ENTITLED"}, status=status.HTTP_403_FORBIDDEN)
    try:
        # ARCH-03 tail: the КП PDF is rendered by WeasyPrint, which must NEVER run inline in the
        # ASGI request thread. Mirror the download-pdf action — stream the persisted (frozen-on-send)
        # PDF if present, else run only the cheap render guards synchronously (surface the 409) and
        # enqueue the idempotent off-thread render with 202 + Retry-After. XLSX/CSV are light and
        # stay synchronous (they carry the seller's internal cost/margin sheet, not a client PDF).
        if export_format == "pdf":
            return _pdf_export_or_generating(quote)
        return export_quote(quote, export_format, include_costs=include_costs)
    except ValueError as exc:
        code = str(exc)
        # Loss-prevention / claim guards (HOLE 2): a КП with no FX rate, below cost, or unclaimed
        # must not render to a downloadable client document — surface the specific 409, not a 400.
        if code in ("QUOTE_NOT_CLAIMED", "FX_RATE_MISSING", "QUOTE_BELOW_COST"):
            return Response({"detail": code}, status=status.HTTP_409_CONFLICT)
        return Response(
            {"detail": "UNSUPPORTED_FORMAT", "supported": ["pdf", "xlsx", "csv"]},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _pdf_export_or_generating(quote):
    """Stream the persisted КП PDF, or enqueue an off-thread render + 202 (ARCH-03).

    Freshness rule is intentionally IDENTICAL to the download-pdf action: a persisted
    ``pdf_file`` is streamed as-is (the КП is frozen on send, so it is stable), and its
    absence — the race before the on-send render lands, or a downed worker — triggers the
    cheap synchronous render guards (raising ValueError → 409 in the caller) followed by
    the idempotent enqueue + 202 + Retry-After. No inline WeasyPrint render here.
    """
    from django.http import FileResponse

    from crm.services import QuoteLifecycleService
    from crm.views._pdf import pdf_generating_response

    if quote.pdf_file:
        return FileResponse(
            quote.pdf_file.open("rb"),
            content_type="application/pdf",
            as_attachment=True,
            filename=quote.pdf_file.name.split("/")[-1],
        )
    # Only the cheap guards run synchronously (QUOTE_NOT_CLAIMED / FX_RATE_MISSING /
    # QUOTE_BELOW_COST) so a broken КП still 409s; the heavy render goes off-thread.
    QuoteLifecycleService.assert_pdf_renderable(quote.pk)
    return pdf_generating_response("quote", quote.pk)
