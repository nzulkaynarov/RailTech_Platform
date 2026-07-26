"""Unauthenticated public surface for an ISSUED generated document (letter/report).

Mirrors the public КП surface (crm/views/quotes/public.py): AllowAny + a scoped throttle,
resolve by secret token, run the reachability gate (ONLY an ISSUED, non-revoked, non-expired
document is served — a DRAFT/CANCELLED never leaks), then content-negotiate:
  * a browser (Accept: text/html, no ?export=pdf) → a self-contained branded HTML page showing the
    document's frozen `rendered_html` snapshot (no cost/margin data lives on a generated document);
  * ?export=pdf OR Accept: application/pdf → the PDF (unchanged ARCH-03 202 pattern — never runs
    WeasyPrint inline in this anonymous thread).

Rule 8: this view is thin — resolve by token, gate via the service, stream/render.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.file_streaming import stream_file_field
from crm.models import GeneratedDocument

# ARCH-03: race-window polling hints for the public document PDF (small polling constants).
PUBLIC_PDF_RETRY_AFTER_SECONDS = 2
PUBLIC_PDF_MAX_AUTO_RETRIES = 5

# Human-facing copy for each unavailable-link reason (browser HTML rendering).
_UNAVAILABLE_COPY = {
    "DOCUMENT_LINK_REVOKED": (
        "Ссылка отозвана",
        "Эта ссылка на документ больше недействительна. Запросите у отправителя актуальную ссылку.",
    ),
    "DOCUMENT_LINK_EXPIRED": (
        "Срок ссылки истёк",
        "Срок действия ссылки на этот документ истёк. Запросите у отправителя обновлённую ссылку.",
    ),
    "NOT_FOUND": (
        "Ссылка не найдена",
        "Документ по этой ссылке не найден. Проверьте ссылку или запросите новую у отправителя.",
    ),
}


def _resolve_document(token):
    """Fetch the document for a public token, or None."""
    return (
        GeneratedDocument.objects.select_related("status", "company", "deal")
        .filter(public_access_token=token)
        .first()
    )


def _unavailable(request, code, http_status):
    """Content-negotiated 404/410 for an unreachable link: friendly HTML for browsers, JSON else."""
    from django.shortcuts import render

    if "text/html" in request.META.get("HTTP_ACCEPT", ""):
        title, message = _UNAVAILABLE_COPY.get(code, _UNAVAILABLE_COPY["NOT_FOUND"])
        return render(
            request, "public/quote_unavailable.html", {"title": title, "message": message}, status=http_status
        )
    return Response({"detail": code}, status=http_status)


class PublicDocumentView(APIView):
    """Content-negotiated public generated document: branded HTML page or PDF by token."""

    permission_classes = [AllowAny]
    authentication_classes = []  # anonymous surface: no session auth ⇒ no CSRF
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_document"

    @extend_schema(
        summary="Public generated-document page (HTML) or PDF by token",
        responses={
            200: OpenApiResponse(description="Document page (browser HTML) or PDF (?export=pdf)"),
            202: OpenApiResponse(description="PDF still rendering off-thread — retry after Retry-After seconds"),
            404: OpenApiResponse(description="Unknown token or not an issued document"),
            410: OpenApiResponse(description="Public link revoked or expired"),
        },
        tags=["CRM"],
    )
    def get(self, request, token):
        from crm.services.generated_documents import public_document_gate

        document = _resolve_document(token)
        code = public_document_gate(document)
        if code == "NOT_FOUND":
            return _unavailable(request, code, status.HTTP_404_NOT_FOUND)
        if code is not None:
            return _unavailable(request, code, status.HTTP_410_GONE)

        wants_pdf = request.GET.get("export") == "pdf" or "application/pdf" in request.META.get("HTTP_ACCEPT", "")
        wants_html = "text/html" in request.META.get("HTTP_ACCEPT", "")
        if wants_html and not wants_pdf:
            return self._render_page(request, document)
        return self._stream_pdf(request, document)

    def _render_page(self, request, document):
        from django.shortcuts import render

        from crm.services.documents import document_brand_context
        from crm.services.generated_documents import _brand_context_from_snapshot

        # Read the SAME brand the PDF renders from: an ISSUED document freezes its letterhead into
        # brand_snapshot, and _render_generated_pdf renders off it — so this public HTML twin must
        # too, or the on-screen page and the downloadable PDF diverge after a later company edit.
        # Fall back to the live context only for docs issued before the snapshot column existed.
        brand = (
            _brand_context_from_snapshot(document.brand_snapshot)
            if document.brand_snapshot
            else document_brand_context(document.company)
        )
        context = {
            "document": document,
            "company": document.company,
            "download_url": "?export=pdf",
            **brand,
        }
        return render(request, "public/document_view.html", context)

    def _stream_pdf(self, request, document):
        if not document.pdf_file:
            from crm.tasks import render_document_pdf

            render_document_pdf.delay("generated", document.id)
            return self._pdf_generating_response(request)
        return stream_file_field(document.pdf_file)

    @staticmethod
    def _pdf_generating_response(request):
        """202 telling the caller the PDF is still rendering off-thread (content-negotiated)."""
        from django.shortcuts import render

        retry_after = PUBLIC_PDF_RETRY_AFTER_SECONDS
        wants_html = "text/html" in request.META.get("HTTP_ACCEPT", "")
        if wants_html:
            try:
                attempt = max(0, int(request.GET.get("r", 0)))
            except (TypeError, ValueError):
                attempt = 0
            response = render(
                request,
                "public/quote_generating.html",
                {
                    "retry_after": retry_after,
                    "auto_retry": attempt < PUBLIC_PDF_MAX_AUTO_RETRIES,
                    "next_query": f"?export=pdf&r={attempt + 1}",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        else:
            response = Response({"detail": "GENERATING", "retry_after": retry_after}, status=status.HTTP_202_ACCEPTED)
        response["Retry-After"] = str(retry_after)
        return response
