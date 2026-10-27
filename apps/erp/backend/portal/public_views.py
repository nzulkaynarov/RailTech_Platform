"""Unauthenticated public portal surfaces for quotes and documents.

M2-ERP-03: Consolidated public acceptance surface and 202-PDF handling in the portal app.
Content-negotiated by token:
  * a browser (Accept: text/html, no ?export=pdf) -> server-rendered HTML page (quote or document);
  * ?export=pdf OR Accept: application/pdf OR bare/JSON -> PDF (202 + Retry-After if rendering off-thread).
Plus quote action endpoints (POST, JSON): viewed beacon, request-code, accept, reject.
"""

from documents.models import GeneratedDocument
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from sales.models import Contract, Quote

from core.file_streaming import stream_file_field
from crm.constants import QuoteStatusCode

# ARCH-03: race-window polling hints for public PDF downloads.
PUBLIC_PDF_RETRY_AFTER_SECONDS = 2
PUBLIC_PDF_MAX_AUTO_RETRIES = 5

_UNAVAILABLE_COPY = {
    "QUOTE_LINK_REVOKED": (
        "Ссылка отозвана",
        "Эта ссылка на коммерческое предложение больше недействительна. Запросите у поставщика актуальную ссылку.",
    ),
    "QUOTE_LINK_EXPIRED": (
        "Срок ссылки истёк",
        "Срок действия этого коммерческого предложения истёк. Запросите у поставщика обновлённое предложение.",
    ),
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
        "Документ или предложение по этой ссылке не найдены. Проверьте ссылку или запросите новую у отправителя.",
    ),
}


def _resolve_quote(token: str):
    """Fetch quote by public token or None."""
    return Quote.objects.select_related("deal", "deal__company", "status").filter(public_access_token=token).first()


def _resolve_document(token: str):
    """Fetch generated document by public access token or None."""
    return (
        GeneratedDocument.objects.select_related("status", "company", "deal").filter(public_access_token=token).first()
    )


def _gate_error(quote):
    """Return reachability error code or None if live."""
    from crm.services.quotes import public_quote_gate

    return public_quote_gate(quote)


def _client_ip(request) -> str:
    """Best-effort client IP."""
    return request.META.get("REMOTE_ADDR", "") or ""


def _mask_email(email: str) -> str:
    """Mask email for hint display (e.g. aziz@acme.uz -> a***@acme.uz)."""
    if not email or "@" not in email:
        return "вашу почту"
    local, _, domain = email.partition("@")
    masked = (local[0] + "***") if local else "***"
    return f"{masked}@{domain}"


def _unavailable(request, code: str, http_status: int):
    """Content-negotiated 404/410 response for an unreachable link: HTML for browsers, JSON else."""
    from django.shortcuts import render

    if "text/html" in request.META.get("HTTP_ACCEPT", ""):
        title, message = _UNAVAILABLE_COPY.get(code, _UNAVAILABLE_COPY["NOT_FOUND"])
        return render(
            request, "public/quote_unavailable.html", {"title": title, "message": message}, status=http_status
        )
    return Response({"detail": code}, status=http_status)


def _newer_sent_version(quote):
    """Number of newer sent version of quote on the same deal, if any."""
    newer = (
        Quote.objects.filter(deal_id=quote.deal_id, version__gt=quote.version)
        .filter(status__code__in=(QuoteStatusCode.SENT, QuoteStatusCode.APPROVED, QuoteStatusCode.REJECTED))
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    return newer


class _PublicQuoteBase(APIView):
    """Shared config for public anonymous quote views (AllowAny, no auth/CSRF, throttled)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]

    def _gate_or_response(self, request, token):
        quote = _resolve_quote(token)
        code = _gate_error(quote)
        if code == "NOT_FOUND":
            return None, _unavailable(request, code, status.HTTP_404_NOT_FOUND)
        if code is not None:
            return None, _unavailable(request, code, status.HTTP_410_GONE)
        return quote, None


class PublicQuotePageScriptView(APIView):
    """Serve public quote page JS from same origin (CSP script-src 'self')."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(exclude=True)
    def get(self, request):
        from django.shortcuts import render

        response = render(request, "crm/quote_public_page.js", content_type="application/javascript; charset=utf-8")
        response["Cache-Control"] = "public, max-age=3600"
        return response


class PublicQuoteView(_PublicQuoteBase):
    """Content-negotiated public quote view: HTML for browsers, PDF for downloads."""

    throttle_scope = "public_quote"

    @extend_schema(
        summary="Public КП page (HTML) or PDF by token",
        responses={
            200: OpenApiResponse(description="Client КП page (browser HTML) or client-projection PDF (?export=pdf)"),
            202: OpenApiResponse(description="PDF still rendering off-thread — retry after Retry-After seconds"),
            404: OpenApiResponse(description="Unknown or not-yet-sent token"),
            410: OpenApiResponse(description="Public link revoked or expired"),
        },
        tags=["Portal"],
    )
    def get(self, request, token):
        quote, gate_response = self._gate_or_response(request, token)
        if gate_response is not None:
            return gate_response

        wants_pdf = request.GET.get("export") == "pdf" or "application/pdf" in request.META.get("HTTP_ACCEPT", "")
        wants_html = "text/html" in request.META.get("HTTP_ACCEPT", "")
        if wants_html and not wants_pdf:
            return self._render_page(request, quote)
        return self._stream_pdf(request, quote)

    def _render_page(self, request, quote):
        from django.shortcuts import render

        from crm.services.documents import public_quote_page_context
        from crm.services.quotes._shared import resolve_quote_recipient

        context = public_quote_page_context(quote)
        recipient = resolve_quote_recipient(quote)
        status_code = quote.status.code if quote.status else None
        context.update(
            {
                "token": quote.public_access_token,
                "page_js_url": "/api/v1/public/quote-page.js",
                "recipient_hint": _mask_email(recipient[0]) if recipient else "вашу почту",
                "is_open": status_code == QuoteStatusCode.SENT,
                "is_approved": status_code == QuoteStatusCode.APPROVED,
                "is_rejected": status_code == QuoteStatusCode.REJECTED,
                "superseded_by_version": _newer_sent_version(quote),
            }
        )
        return render(request, "crm/quote_public_page.html", context)

    def _stream_pdf(self, request, quote):
        if not quote.pdf_file:
            from crm.tasks import render_document_pdf

            render_document_pdf.delay("quote", quote.pk)
            return self._pdf_generating_response(request)
        return stream_file_field(quote.pdf_file)

    @staticmethod
    def _pdf_generating_response(request):
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


class PublicQuoteViewedView(_PublicQuoteBase):
    """Browser beacon marking genuine open of the quote."""

    throttle_scope = "public_quote_view"

    @extend_schema(summary="Mark public КП as viewed (beacon)", tags=["Portal"], request=None, responses={204: None})
    def post(self, request, token):
        quote, gate_response = self._gate_or_response(request, token)
        if gate_response is not None:
            return gate_response
        from crm.services.public_page import record_quote_view

        record_quote_view(quote, request_ip=_client_ip(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicQuoteRequestCodeView(_PublicQuoteBase):
    """Email one-time verification code for quote acceptance."""

    throttle_scope = "public_quote_code"

    @extend_schema(
        summary="Request КП acceptance code",
        tags=["Portal"],
        request=None,
        responses={200: inline_serializer("PublicCodeSent", fields={"detail": drf_serializers.CharField()})},
    )
    def post(self, request, token):
        quote, gate_response = self._gate_or_response(request, token)
        if gate_response is not None:
            return gate_response
        from crm.services.public_page import issue_acceptance_code

        issue_acceptance_code(quote, request_ip=_client_ip(request))
        return Response({"detail": "CODE_SENT_IF_RECIPIENT_EXISTS"}, status=status.HTTP_200_OK)


class PublicQuoteAcceptView(_PublicQuoteBase):
    """Accept quote with email verification code."""

    throttle_scope = "public_quote_accept"

    @extend_schema(
        summary="Accept КП with email code",
        tags=["Portal"],
        request=inline_serializer("PublicQuoteAcceptRequest", fields={"code": drf_serializers.CharField()}),
        responses={
            200: inline_serializer(
                "PublicQuoteAccepted",
                fields={"detail": drf_serializers.CharField(), "contract_number": drf_serializers.CharField()},
            ),
            400: OpenApiResponse(description="Wrong or expired code (error code from verify_code_and_accept)"),
        },
    )
    def post(self, request, token):
        quote, gate_response = self._gate_or_response(request, token)
        if gate_response is not None:
            return gate_response
        from crm.services.public_page import verify_code_and_accept

        code = (request.data or {}).get("code", "")
        accepted, error = verify_code_and_accept(quote, code, request_ip=_client_ip(request))
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        contract = Contract.objects.filter(deal=accepted.deal, quote=accepted).order_by("-id").first()
        return Response(
            {"detail": "ACCEPTED", "contract_number": getattr(contract, "number", "") or "—"},
            status=status.HTTP_200_OK,
        )


class PublicQuoteRejectView(_PublicQuoteBase):
    """Reject quote from public page with a reason."""

    throttle_scope = "public_quote_accept"

    @extend_schema(
        summary="Reject КП with reason",
        tags=["Portal"],
        request=inline_serializer("PublicQuoteRejectRequest", fields={"reason": drf_serializers.CharField()}),
        responses={
            200: inline_serializer("PublicQuoteRejected", fields={"detail": drf_serializers.CharField()}),
            400: OpenApiResponse(description="Reason missing or quote not rejectable (error code)"),
        },
    )
    def post(self, request, token):
        quote, gate_response = self._gate_or_response(request, token)
        if gate_response is not None:
            return gate_response
        from crm.services.public_page import reject_from_public_page

        reason = (request.data or {}).get("reason", "")
        rejected, error = reject_from_public_page(quote, reason, request_ip=_client_ip(request))
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"detail": "REJECTED"}, status=status.HTTP_200_OK)


class PublicDocumentView(APIView):
    """Public content-negotiated view for an ISSUED generated document: HTML page or PDF."""

    permission_classes = [AllowAny]
    authentication_classes = []
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
        tags=["Portal"],
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
