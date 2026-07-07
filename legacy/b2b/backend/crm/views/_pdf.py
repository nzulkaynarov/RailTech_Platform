"""Shared 202-pattern helper for authenticated document-PDF endpoints (ARCH-03).

PublicQuoteView set the contract: a PDF that is not persisted yet is never rendered
inline in the request thread — the idempotent off-thread render task is enqueued and
the caller polls with a Retry-After hint. This module gives the authenticated
download/generate endpoints (КП, contract, invoice, act, deal export) the same
behavior; the SPA polls via lib/download.ts.
"""

from rest_framework import status
from rest_framework.response import Response

# Same polling hint as the public endpoint (PUBLIC_PDF_RETRY_AFTER_SECONDS).
PDF_RETRY_AFTER_SECONDS = 2


def pdf_generating_response(doc_type: str, doc_id: int) -> Response:
    """Enqueue the idempotent off-thread render and tell the caller to poll."""
    from crm.tasks import render_document_pdf

    render_document_pdf.delay(doc_type, doc_id)
    response = Response(
        {"detail": "GENERATING", "retry_after": PDF_RETRY_AFTER_SECONDS},
        status=status.HTTP_202_ACCEPTED,
    )
    response["Retry-After"] = str(PDF_RETRY_AFTER_SECONDS)
    return response
