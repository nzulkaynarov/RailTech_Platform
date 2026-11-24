"""Документ по ссылке из письма (ДК-1, ДК-2, ADR-0030): `/api/portal/v1/doc-links/*`.

Гость видит один документ; любое действие — после кода на адрес получателя, код открывает сессию контакта. Вьюхи тонкие:
выпуск, состояния, код и журнал — `portal.services.doc_links`. `open`, `pdf`, `code`, `verify` открыты без сессии
(токен в теле, лимит по IP); `act` требует сессии контакта той же компании и проходит все проверки кабинета: модуль,
право действовать, принятие оферты.
"""

from __future__ import annotations

import logging

from django.http import Http404
from portal import projections
from portal.authentication import PortalAuthentication
from portal.client_ip import client_ip
from portal.exceptions import PortalConflict, PortalValidationError, portal_exception_handler
from portal.models import DocumentLinkEvent
from portal.permissions import ANY_MODULE
from portal.serializers import QuoteLineSerializer
from portal.services import doc_links
from portal.services.doc_link_kinds import spec_for
from portal.throttles import PortalDocLinkRateThrottle, PortalLoginRateThrottle
from portal.views import BasePortalView, _session_response
from rest_framework import exceptions, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from core.file_streaming import stream_file_field

logger = logging.getLogger(__name__)

TEXT_MAX_LENGTH = 2000


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(min_length=1, max_length=200)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError("VALIDATION_ERROR")
        return super().to_internal_value(data)


class VerifySerializer(TokenSerializer):
    code = serializers.RegexField(r"^\d{6}$")


class ActSerializer(TokenSerializer):
    action = serializers.ChoiceField(choices=["accept", "reject", "question"])
    text = serializers.CharField(required=False, allow_blank=True, max_length=TEXT_MAX_LENGTH, trim_whitespace=True)


def _optional_session(request):
    """Сессия портала, если она есть и жива; иначе `None` — гость. Битая или просроченная сессия — тоже гость."""
    try:
        authenticated = PortalAuthentication().authenticate(request)
    except exceptions.AuthenticationFailed:
        return None
    return authenticated[1] if authenticated else None


def _link_or_404(raw_token: str):
    link = doc_links.find_link(raw_token)
    if link is None or link.document is None:
        raise Http404  # неизвестный токен — всегда один и тот же ответ
    return link


def _live_link(raw_token: str):
    link = _link_or_404(raw_token)
    doc_links.raise_if_gone(link)
    return link


def _document(link, ctx: doc_links.ClientContext, modules=()) -> dict:
    """Тело `DocLinkView`: клиентская проекция КП и то, что кнопки могут (из фактов КП и прав контакта)."""
    spec = spec_for(link)
    doc = link.document
    company = spec.deal(doc).company
    code = spec.currency_code(doc)
    decide = doc_links.availability(link, ctx, modules)
    body = {
        "kind": link.kind,
        "number": spec.number(doc),
        "version": getattr(doc, "version", 1),
        "from_name": spec.seller_name(doc),
        "to_name": company.name if company is not None else "",
        "total": projections.money(spec.total(doc), code),
        "valid_until": None,
        "state": spec.state(doc),
        "link_expires_at": link.expires_at.isoformat(),
        "recipient_hint": doc_links.mask_email(link.recipient_email),
        "session": ctx.relation,
        "decide": decide,
        "ask": decide,
        "actions": list(spec.actions),
        "lines": [],
        **spec.extra(doc),
    }
    if link.kind == "quote":
        body.update(
            {
                "subtotal": projections.quote_subtotal(doc),
                "vat": projections.quote_vat(doc),
                "payment_terms": doc.payment_terms or None,
                "delivery_days": doc.effective_delivery_lead_time_days or None,
                "delivery_note": doc.delivery_note or None,
                "lines": QuoteLineSerializer(projections.quote_lines(doc), many=True).data,
            }
        )
    return body


def accept_quote(quote, contact, ip: str) -> None:
    from crm.services.public_page import _send_accepted_next_step_email
    from crm.services.quotes import QuoteLifecycleService

    try:
        accepted = QuoteLifecycleService.accept_quote_as_contact(
            quote.pk, contact_email=contact.email, request_ip=ip, portal_contact=contact
        )
    except ValueError:
        raise PortalConflict("QUOTE_FINALIZED")  # успели решить из другой вкладки
    if contact.email:
        _send_accepted_next_step_email(accepted, contact.email)


def reject_quote(quote, contact, reason: str, ip: str) -> None:
    from crm.services.quotes.lifecycle_accept import perform_quote_rejection

    try:
        perform_quote_rejection(
            quote.pk,
            rejected_by_user=None,
            reason=reason,
            contact_email=contact.email,
            request_ip=ip,
            portal_contact=contact,
        )
    except ValueError:
        raise PortalConflict("QUOTE_FINALIZED")


def _ua(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")


class _PublicDocLinkView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [PortalDocLinkRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler


class DocLinkOpenView(_PublicDocLinkView):
    """POST /doc-links/open {token} — документ гостю или вошедшему контакту; открытие пишется в журнал ссылки."""

    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        link = _live_link(serializer.validated_data["token"])
        session = _optional_session(request)
        ctx = doc_links.client_context(link, session)
        modules = getattr(request, "portal_modules", ()) if session is not None else ()
        doc_links.record_open(link, ip=client_ip(request), user_agent=_ua(request))
        return Response(_document(link, ctx, modules))


class DocLinkPdfView(_PublicDocLinkView):
    """POST /doc-links/pdf {token} — тот же PDF, что ушёл письмом; ещё собирается — 202 и `Retry-After`."""

    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        link = _live_link(serializer.validated_data["token"])
        doc = link.document
        spec = spec_for(link)
        if not spec.pdf_file(doc):
            from crm.tasks import render_document_pdf

            render_document_pdf.delay(link.kind, doc.pk)
            response = Response({"detail": "GENERATING"}, status=status.HTTP_202_ACCEPTED)
            response["Retry-After"] = "2"
            return response
        return stream_file_field(spec.pdf_file(doc))


class DocLinkCodeView(_PublicDocLinkView):
    """POST /doc-links/code {token} — код на адрес получателя; адреса в запросе нет."""

    throttle_classes = [PortalLoginRateThrottle]

    def post(self, request):
        serializer = TokenSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        link = _live_link(serializer.validated_data["token"])
        sent = doc_links.request_code(link, ip=client_ip(request), user_agent=_ua(request))
        return Response(sent, status=status.HTTP_202_ACCEPTED)


class DocLinkVerifyView(_PublicDocLinkView):
    """POST /doc-links/verify {token, code} — код погашен, сессия контакта-получателя открыта."""

    throttle_classes = [PortalLoginRateThrottle]

    def post(self, request):
        serializer = VerifySerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        link = _live_link(serializer.validated_data["token"])
        session, session_token = doc_links.verify_code(
            link, serializer.validated_data["code"], ip=client_ip(request), user_agent=_ua(request)
        )
        return _session_response(request, session, session_token)


class DocLinkActView(BasePortalView):
    """POST /doc-links/act {token, action, text?} — решение или вопрос; права — контакта сессии, не шире.

    Модуль кабинета зависит от вида документа (КП — «Предложения», договор — «Договоры», акт — «Акты»), поэтому его
    проверяет сама вьюха после того, как нашла ссылку; действия, которых у этого вида нет, — 422 `VALIDATION_ERROR`:
    ссылка договора не принимает решений по КП и наоборот.
    """

    required_module = ANY_MODULE

    def post(self, request):
        serializer = ActSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        data = serializer.validated_data
        link = _live_link(data["token"])
        spec = spec_for(link)
        doc = link.document
        action = data["action"]
        if action not in spec.actions:
            raise PortalValidationError("VALIDATION_ERROR")
        session = request.portal_session
        ctx = doc_links.client_context(link, session)
        if ctx.relation != "member":
            raise PermissionDenied("FORBIDDEN")  # сессия другой компании ничего по этой ссылке не делает
        if spec.module not in set(request.portal_modules):
            raise PermissionDenied("MODULE_REQUIRED")
        spec.assert_actionable(doc)
        contact = request.portal_contact
        text = (data.get("text") or "").strip()
        ip = client_ip(request)
        if action in ("reject", "question") and not text:
            raise PortalValidationError("REASON_REQUIRED" if action == "reject" else "TEXT_REQUIRED")
        spec.perform(doc, action, contact=contact, text=text, ip=ip)
        doc_links.record_event(link, DocumentLinkEvent.Event.ACTION, ip=ip, user_agent=_ua(request), action=action)
        link = doc_links.find_link(data["token"])
        return Response(_document(link, ctx, request.portal_modules))
