"""Unauthenticated public КП surface (view/download + Wave-A page & offline acceptance).

Content-negotiated by token:
  * a browser (Accept: text/html, no ?export=pdf) → the server-rendered КП PAGE (Wave A) — the
    client reads it and acts on it (accept / reject / download / ask), no SPA, no login;
  * ?export=pdf  OR  Accept: application/pdf  OR  a bare/JSON caller → the client-projection PDF
    (unchanged ARCH-03 202 pattern; never runs WeasyPrint inline in this anonymous thread).

Plus the Wave-A action endpoints (POST, JSON): viewed beacon, request-code, accept, reject.
Rule 8: these views are thin — resolve by token, run the reachability gate, call ONE service.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.file_streaming import stream_file_field
from crm.constants import QuoteStatusCode
from crm.models import Quote

# ARCH-03: race-window polling hints for the public КП PDF. When a client opens the emailed
# link before the off-thread render (F1.6) has landed, we ask them to retry rather than run
# WeasyPrint inline in this anonymous request thread. Small polling constants, not business data.
PUBLIC_PDF_RETRY_AFTER_SECONDS = 2
PUBLIC_PDF_MAX_AUTO_RETRIES = 5

# Human-facing copy for each unavailable-link reason (shared by all public views for browsers).
_UNAVAILABLE_COPY = {
    "QUOTE_LINK_REVOKED": (
        "Ссылка отозвана",
        "Эта ссылка на коммерческое предложение больше недействительна. " "Запросите у поставщика актуальную ссылку.",
    ),
    "QUOTE_LINK_EXPIRED": (
        "Срок ссылки истёк",
        "Срок действия этого коммерческого предложения истёк. Запросите у поставщика обновлённое предложение.",
    ),
    "NOT_FOUND": (
        "Ссылка не найдена",
        "Коммерческое предложение по этой ссылке не найдено. Проверьте ссылку или запросите новую у поставщика.",
    ),
}


def _resolve_quote(token):
    """Fetch the quote for a public token, or None. Shared by every public view."""
    return Quote.objects.select_related("deal", "deal__company", "status").filter(public_access_token=token).first()


def _gate_error(quote):
    """Return the reachability error code (NOT_FOUND / QUOTE_LINK_*) or None if the link is live."""
    from crm.services.quotes import public_quote_gate

    return public_quote_gate(quote)


def _client_ip(request):
    """Best-effort client IP for the acceptance audit trail (not a trust anchor)."""
    return request.META.get("REMOTE_ADDR", "") or ""


def _mask_email(email):
    """`aziz@acme.uz` → `a***@acme.uz`. Shown to the link-holder as a which-inbox hint only."""
    if not email or "@" not in email:
        return "вашу почту"
    local, _, domain = email.partition("@")
    masked = (local[0] + "***") if local else "***"
    return f"{masked}@{domain}"


def _unavailable(request, code, http_status):
    """Content-negotiated 404/410 for an unreachable link: friendly HTML for browsers, JSON else."""
    from django.shortcuts import render

    if "text/html" in request.META.get("HTTP_ACCEPT", ""):
        title, message = _UNAVAILABLE_COPY.get(code, _UNAVAILABLE_COPY["NOT_FOUND"])
        return render(
            request, "public/quote_unavailable.html", {"title": title, "message": message}, status=http_status
        )
    return Response({"detail": code}, status=http_status)


class PublicQuotePageScriptView(APIView):
    """Serve the public КП page JS from the SAME origin (CSP script-src 'self').

    The JS is served by Django (not from a `static/` dir — that path is gitignored, so it would
    never be committed/collected) as a tokenless, cacheable, quote-agnostic asset: the page passes
    the token via a DOM data-attribute, so ONE script serves every КП. No auth (anonymous page).
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(exclude=True)
    def get(self, request):
        from django.shortcuts import render

        response = render(request, "crm/quote_public_page.js", content_type="application/javascript; charset=utf-8")
        response["Cache-Control"] = "public, max-age=3600"
        return response


class _PublicQuoteBase(APIView):
    """Shared config for every anonymous public КП view (no auth → no CSRF; AllowAny; throttled)."""

    permission_classes = [AllowAny]
    authentication_classes = []  # anonymous surface: no session auth ⇒ no CSRF gate on the POSTs
    throttle_classes = [ScopedRateThrottle]

    def _gate_or_response(self, request, token):
        """Resolve + gate. Returns (quote, None) when live, or (None, response) to return."""
        quote = _resolve_quote(token)
        code = _gate_error(quote)
        if code == "NOT_FOUND":
            return None, _unavailable(request, code, status.HTTP_404_NOT_FOUND)
        if code is not None:
            return None, _unavailable(request, code, status.HTTP_410_GONE)
        return quote, None


def _newer_sent_version(quote):
    """Номер более новой РАЗОСЛАННОЙ редакции того же КП, если она есть.

    Считается по факту, без отдельного статуса: «superseded» — это не состояние документа,
    а наличие следующей версии на той же сделке (как «Quote Document version» в Salesforce CPQ,
    где версия — снимок, а живёт одна запись). Учитываются только версии, ДОШЕДШИЕ до клиента
    (SENT/APPROVED/REJECTED): черновик, который продавец ещё правит, ничего не отменяет.
    """
    from crm.models import Quote

    newer = (
        Quote.objects.filter(deal_id=quote.deal_id, version__gt=quote.version)
        .filter(status__code__in=(QuoteStatusCode.SENT, QuoteStatusCode.APPROVED, QuoteStatusCode.REJECTED))
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    return newer


class PublicQuoteView(_PublicQuoteBase):
    """Content-negotiated public КП: HTML page for browsers, client-projection PDF for downloads."""

    throttle_scope = "public_quote"

    @extend_schema(
        summary="Public КП page (HTML) or PDF by token",
        responses={
            200: OpenApiResponse(description="Client КП page (browser HTML) or client-projection PDF (?export=pdf)"),
            202: OpenApiResponse(description="PDF still rendering off-thread — retry after Retry-After seconds"),
            404: OpenApiResponse(description="Unknown or not-yet-sent token"),
            410: OpenApiResponse(description="Public link revoked or expired"),
        },
        tags=["CRM"],
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

    # ── HTML page (Wave A) ──────────────────────────────────────────────
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
                # O2: у ссылки на СТАРУЮ редакцию клиент должен видеть, что цена уже не та.
                # Эталоны (HubSpot recall&edit, Odoo reset-to-draft) переиздают КП по тому же
                # адресу; у нас каждая версия несёт свой токен, поэтому старая ссылка живёт
                # своей жизнью — и без пометки клиент принимал бы устаревшее предложение.
                "superseded_by_version": _newer_sent_version(quote),
            }
        )
        return render(request, "crm/quote_public_page.html", context)

    # ── PDF download (unchanged ARCH-03 behaviour) ──────────────────────
    def _stream_pdf(self, request, quote):
        if not quote.pdf_file:
            from crm.tasks import render_document_pdf

            render_document_pdf.delay("quote", quote.pk)
            return self._pdf_generating_response(request)
        return stream_file_field(quote.pdf_file)

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


class PublicQuoteViewedView(_PublicQuoteBase):
    """Browser BEACON marking a genuine open (fired by page JS, NOT the bare GET)."""

    throttle_scope = "public_quote_view"

    @extend_schema(summary="Mark public КП as viewed (beacon)", tags=["CRM"], request=None, responses={204: None})
    def post(self, request, token):
        quote, gate_response = self._gate_or_response(request, token)
        if gate_response is not None:
            return gate_response
        from crm.services.public_page import record_quote_view

        record_quote_view(quote, request_ip=_client_ip(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicQuoteRequestCodeView(_PublicQuoteBase):
    """Email a one-time acceptance code to the recipient resolved from the QUOTE'S deal."""

    throttle_scope = "public_quote_code"

    @extend_schema(summary="Request КП acceptance code", tags=["CRM"], request=None, responses={200: None})
    def post(self, request, token):
        quote, gate_response = self._gate_or_response(request, token)
        if gate_response is not None:
            return gate_response
        from crm.services.public_page import issue_acceptance_code

        # Enumeration-neutral: identical response whether or not a recipient exists.
        issue_acceptance_code(quote, request_ip=_client_ip(request))
        return Response({"detail": "CODE_SENT_IF_RECIPIENT_EXISTS"}, status=status.HTTP_200_OK)


class PublicQuoteAcceptView(_PublicQuoteBase):
    """Verify the one-time code and accept the КП as the offline contact (коммерческий акцепт)."""

    throttle_scope = "public_quote_accept"

    @extend_schema(summary="Accept КП with email code", tags=["CRM"], responses={200: None})
    def post(self, request, token):
        quote, gate_response = self._gate_or_response(request, token)
        if gate_response is not None:
            return gate_response
        from crm.services.public_page import verify_code_and_accept

        code = (request.data or {}).get("code", "")
        accepted, error = verify_code_and_accept(quote, code, request_ip=_client_ip(request))
        if error is not None:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        from crm.models import Contract

        contract = Contract.objects.filter(deal=accepted.deal, quote=accepted).order_by("-id").first()
        return Response(
            {"detail": "ACCEPTED", "contract_number": getattr(contract, "number", "") or "—"},
            status=status.HTTP_200_OK,
        )


class PublicQuoteRejectView(_PublicQuoteBase):
    """Reject the КП from the public page — required reason (recoverable, link-gated only)."""

    throttle_scope = "public_quote_accept"

    @extend_schema(summary="Reject КП with reason", tags=["CRM"], responses={200: None})
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
