"""Unauthenticated public КП view (view/download by secret token).

Split out of the monolithic ``crm/views/quotes.py`` (ARCH refactor) — behaviour
unchanged. Serves ONLY the client-projection PDF of a SENT (frozen) КП; enforces the
reachability gate (404 unknown / 410 revoked-or-expired) and the ARCH-03 202 pattern
(never runs WeasyPrint inline in this anonymous request thread).
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.file_streaming import stream_file_field
from crm.models import Quote

# ARCH-03: race-window polling hints for the public КП PDF. When a client opens the emailed
# link before the off-thread render (F1.6) has landed, we ask them to retry rather than run
# WeasyPrint inline in this anonymous request thread. Small polling constants, not business data.
PUBLIC_PDF_RETRY_AFTER_SECONDS = 2
PUBLIC_PDF_MAX_AUTO_RETRIES = 5


class PublicQuoteView(APIView):
    """Unauthenticated КП view/download by secret token (client base, CB-public-link).

    Lets an offline or registered client open the КП the seller emailed them WITHOUT a
    login. Streams the CLIENT projection PDF only (quote_pdf.html exposes no margin/cost/
    charges). Only a SENT (frozen) КП with a token is reachable; an unknown token 404s.
    Rate-limited to blunt token brute-forcing despite the 256-bit space.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_quote"

    @extend_schema(
        summary="Public КП view/download by token",
        responses={
            (200, "application/pdf"): OpenApiResponse(description="КП PDF (client projection)"),
            202: OpenApiResponse(description="PDF still rendering off-thread — retry after Retry-After seconds"),
            404: OpenApiResponse(description="Unknown or not-yet-sent token"),
            410: OpenApiResponse(
                description="Public link revoked or expired (QUOTE_LINK_REVOKED / QUOTE_LINK_EXPIRED)"
            ),
        },
        tags=["CRM"],
    )
    def get(self, request, token):
        from crm.services.quotes import public_quote_gate

        quote = Quote.objects.select_related("deal", "status").filter(public_access_token=token).first()
        # Reachability gate (Rule 8): unknown/not-yet-sent → 404 (no info leak); revoked or
        # lapsed (EXPIRED / valid_until / token TTL, audit #17) → 410 GONE. Live → fall through.
        gate_error = public_quote_gate(quote)
        if gate_error == "NOT_FOUND":
            return self._unavailable_response(request, gate_error, status.HTTP_404_NOT_FOUND)
        if gate_error is not None:
            return self._unavailable_response(request, gate_error, status.HTTP_410_GONE)
        if not quote.pdf_file:
            # ARCH-03: NEVER run a synchronous WeasyPrint render in this AllowAny/anonymous
            # request thread — a full sync render here is a DoS-amplification surface. The КП PDF
            # is normally already persisted off-thread on send (F1.6 → send_quote_email); only the
            # race window (client opens the link before the celery task lands) or a downed worker
            # reaches this branch. Enqueue the idempotent render task (it no-ops if the file already
            # exists) and ask the client to retry, instead of rendering inline.
            from crm.tasks import render_document_pdf

            render_document_pdf.delay("quote", quote.pk)
            return self._pdf_generating_response(request)
        return stream_file_field(quote.pdf_file)

    # Human-facing copy for each unavailable-link reason. The public link opens directly in a
    # browser (no SPA in front), and EVERY legit КП link eventually expires — so this is a routine
    # client-facing state, not a rare error. Keep the code in the JSON body for API callers.
    _UNAVAILABLE_COPY = {
        "QUOTE_LINK_REVOKED": (
            "Ссылка отозвана",
            "Эта ссылка на коммерческое предложение больше недействительна. "
            "Запросите у поставщика актуальную ссылку.",
        ),
        "QUOTE_LINK_EXPIRED": (
            "Срок ссылки истёк",
            "Срок действия этого коммерческого предложения истёк. " "Запросите у поставщика обновлённое предложение.",
        ),
        "NOT_FOUND": (
            "Ссылка не найдена",
            "Коммерческое предложение по этой ссылке не найдено. " "Проверьте ссылку или запросите новую у поставщика.",
        ),
    }

    @classmethod
    def _unavailable_response(cls, request, code, http_status):
        """Content-negotiated 404/410 for an unreachable public link.

        A browser (Accept: text/html) opening a revoked/expired/unknown link gets a small
        friendly Russian page (never the raw DRF/JSON error); an API/JSON client gets the
        machine code in `{"detail": CODE}`. Mirrors `_pdf_generating_response`."""
        from django.shortcuts import render

        if "text/html" in request.META.get("HTTP_ACCEPT", ""):
            title, message = cls._UNAVAILABLE_COPY.get(code, cls._UNAVAILABLE_COPY["NOT_FOUND"])
            return render(
                request,
                "public/quote_unavailable.html",
                {"title": title, "message": message},
                status=http_status,
            )
        return Response({"detail": code}, status=http_status)

    @staticmethod
    def _pdf_generating_response(request):
        """202 telling the caller the PDF is still rendering off-thread.

        Content-negotiated: the emailed link opens THIS endpoint directly in a browser (there is
        no SPA page in front of it), so a browser (Accept: text/html) gets a small self-refreshing
        interstitial that auto-retries a few times then offers a manual «Обновить»; an API/JSON
        client gets a compact JSON body. Both carry a Retry-After header.
        """
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
                    "next_query": f"?r={attempt + 1}",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        else:
            response = Response(
                {"detail": "GENERATING", "retry_after": retry_after},
                status=status.HTTP_202_ACCEPTED,
            )
        response["Retry-After"] = str(retry_after)
        return response
