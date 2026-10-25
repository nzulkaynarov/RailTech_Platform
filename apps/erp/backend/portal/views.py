"""Portal API Views (Cabinet → ERP, M2-ERP-01).

Реализация всех эндпоинтов по packages/contracts/openapi/erp-portal.yaml и CONTRACTS §4.
Все ответы отфильтрованы по компании текущей сессии (`request.portal_company`).
Попытка доступа к объекту другой компании возвращает 404 {"detail": "NOT_FOUND"}.
Действия мутации требуют CanAct (can_act=True), иначе 403 {"detail": "FORBIDDEN"}.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone, translation
from integration.services.requisites import REQUISITES_MANAGED_BY_CRM, changed_crm_owned_fields
from parties.models import Contact, active_contact_q
from portal.authentication import PortalAuthentication
from portal.exceptions import PortalBadRequest, PortalConflict, PortalValidationError, portal_exception_handler
from portal.models import PortalUpload
from portal.permissions import CanAct, IsPortalAuthenticated
from portal.projections import (
    annotate_request_sources,
    client_acts_q,
    client_contracts_q,
    client_invoices_q,
    client_quotes_q,
)
from portal.serializers import (
    AcceptanceCodeSentSerializer,
    ActAcceptSerializer,
    ActSerializer,
    CatalogCategorySerializer,
    CatalogItemSerializer,
    CatalogPageSerializer,
    ClientRequestCreateSerializer,
    ClientRequestSerializer,
    CompanySerializer,
    CompanyUpdateSerializer,
    ContractSerializer,
    DeliveryLineSerializer,
    InvoiceSerializer,
    MagicLinkRequestSerializer,
    MagicLinkTokenSerializer,
    MeSerializer,
    PortalDocumentSerializer,
    PortalUploadResponseSerializer,
    QuoteAcceptSerializer,
    QuoteListItemSerializer,
    QuoteSerializer,
    ReasonSerializer,
    TeamInviteSerializer,
    TeamMemberSerializer,
    TelegramAuthSerializer,
)
from portal.services import documents as portal_documents
from portal.services.acceptance import ContactChannelRequired, request_acceptance_code
from portal.services.act_scan import annotate_scan_documents, attach_scan_document, load_scan
from portal.services.invitation import invite_team_member
from portal.services.magic_link import exchange_magic_link, request_magic_link
from portal.services.requests import create_client_request
from portal.services.telegram_auth import authenticate_telegram_user
from portal.throttles import PortalAcceptRateThrottle, PortalLoginRateThrottle, PortalSessionRateThrottle
from rest_framework import exceptions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from sales.models import DeliveryLine
from sales.services.delivery_lines import accept_delivery_line, dispute_delivery_line, sync_company_delivery_lines

from catalog.published import project, project_many, published_products
from core.i18n import supported_languages
from crm.constants import ActStatusCode, QuoteStatusCode
from crm.models import Act, Contract, Deal, Invoice, Quote
from crm.services.billing import reject_act, sign_act
from crm.services.contracts import sign_contract_by_client
from crm.services.public_page import verify_code_and_accept
from crm.services.quotes.access import _EXPIRED_STATUS_CODE
from crm.services.quotes.lifecycle_accept import perform_quote_rejection

logger = logging.getLogger(__name__)


def _portal_cookie_attrs() -> dict:
    """Атрибуты cookie сессии: `PORTAL_COOKIE_SAMESITE=None` (Telegram Mini App) требует `Secure` и в DEBUG."""
    samesite = getattr(settings, "PORTAL_COOKIE_SAMESITE", "Lax")
    return {"samesite": samesite, "secure": samesite == "None" or not settings.DEBUG}


def _set_portal_cookie(response: Response, token: str) -> Response:
    cookie_name = getattr(settings, "PORTAL_SESSION_COOKIE_NAME", "portal_session")
    max_age = getattr(settings, "PORTAL_SESSION_MAX_AGE_DAYS", 14) * 86400
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        path="/api/portal",
        **_portal_cookie_attrs(),
    )
    return response


def _delete_portal_cookie(response: Response) -> Response:
    # Cookie с SameSite=None браузер принимает к удалению только с теми же `SameSite=None; Secure`.
    cookie_name = getattr(settings, "PORTAL_SESSION_COOKIE_NAME", "portal_session")
    # `delete_cookie` не принимает `secure`, поэтому — тот же set_cookie с нулевым сроком.
    response.set_cookie(
        key=cookie_name,
        value="",
        max_age=0,
        expires="Thu, 01 Jan 1970 00:00:00 GMT",
        httponly=True,
        path="/api/portal",
        **_portal_cookie_attrs(),
    )
    return response


def _parse_reason(data) -> str:
    """Причина из тела `Reason`: пустая — 422 `REASON_REQUIRED`, длиннее лимита контракта — 422 `VALIDATION_ERROR`."""
    serializer = ReasonSerializer(data=data)
    if not serializer.is_valid():
        too_long = any(error.code == "max_length" for error in serializer.errors.get("reason", []))
        raise PortalValidationError("VALIDATION_ERROR" if too_long else "REASON_REQUIRED")
    return serializer.validated_data["reason"].strip()


class BasePortalView(APIView):
    """Базовый класс для портальных эндпоинтов с аутентификацией."""

    authentication_classes = [PortalAuthentication]
    permission_classes = [IsPortalAuthenticated, CanAct]
    # Лимит по сессии вместо общего анонимного 20/мин по IP (FIX-15, P-14).
    throttle_classes = [PortalSessionRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def permission_denied(self, request, message=None, code=None):
        if not getattr(request, "portal_session", None):
            raise exceptions.NotAuthenticated("UNAUTHORIZED")
        super().permission_denied(request, message=message, code=code)


# ── 1. Auth & Session ────────────────────────────────────────────────────────


class TelegramAuthView(APIView):
    """POST /auth/telegram — Вход из Telegram Mini App."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [PortalLoginRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def post(self, request):
        serializer = TelegramAuthSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("INVALID_INIT_DATA")

        init_data = serializer.validated_data["init_data"]
        ip = request.META.get("REMOTE_ADDR")
        ua = request.META.get("HTTP_USER_AGENT", "")

        session, token = authenticate_telegram_user(
            init_data,
            ip_address=ip,
            user_agent=ua,
        )

        me_data = {
            "contact": TeamMemberSerializer(session.contact).data,
            "company": CompanySerializer(session.company).data,
            "can_act": session.contact.can_act,
            "auth_method": "telegram",
        }
        res = Response(MeSerializer(me_data).data, status=status.HTTP_200_OK)
        return _set_portal_cookie(res, token)


class MagicLinkRequestView(APIView):
    """POST /auth/magic-link — Запрос ссылки для входа по email."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [PortalLoginRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def post(self, request):
        serializer = MagicLinkRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")

        email = serializer.validated_data["email"]
        request_magic_link(email)
        return Response({"status": "ok", "sent": True, "email": email}, status=status.HTTP_200_OK)


def _exchange_magic_token(request, token: str) -> Response:
    """Обмен токена ссылки входа на сессию (`POST /auth/magic`)."""
    session, session_token = exchange_magic_link(
        token,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
    me_data = {
        "contact": TeamMemberSerializer(session.contact).data,
        "company": CompanySerializer(session.company).data,
        "can_act": session.contact.can_act,
        "auth_method": "magic_link",
    }
    res = Response(MeSerializer(me_data).data, status=status.HTTP_200_OK)
    return _set_portal_cookie(res, session_token)


class MagicLinkTokenExchangeView(APIView):
    """POST /auth/magic {token} — обмен токена из фрагмента ссылки входа (`/auth/magic#token=…`) на сессию.

    Токен приходит в теле: ни путь, ни query не несут секрета, значит журналы серверов и прокси его не видят.
    Архивная компания — 403 `FORBIDDEN`, просроченный, использованный или неизвестный токен — 410.
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [PortalLoginRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def post(self, request):
        serializer = MagicLinkTokenSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        return _exchange_magic_token(request, serializer.validated_data["token"])


class LogoutView(APIView):
    """POST /auth/logout — Завершение сессии портала."""

    authentication_classes = [PortalAuthentication]
    permission_classes = []
    throttle_classes = [PortalSessionRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def post(self, request):
        session = getattr(request, "portal_session", None)
        if session:
            session.delete()
        res = Response(status=status.HTTP_204_NO_CONTENT)
        return _delete_portal_cookie(res)


# ── 2. Me ───────────────────────────────────────────────────────────────────


class MeView(BasePortalView):
    """GET /me — Текущий профиль сессии (контакт, компания, права)."""

    def get(self, request):
        contact = request.portal_contact
        company = request.portal_company
        session = request.portal_session

        me_data = {
            "contact": TeamMemberSerializer(contact).data,
            "company": CompanySerializer(company).data,
            "can_act": contact.can_act,
            "auth_method": session.auth_method,
        }
        return Response(MeSerializer(me_data).data)


# ── 3. Requests ─────────────────────────────────────────────────────────────


def _requests_queryset(company):
    """Запросы компании (сделки) с тем, что нужно сериализатору, без N+1."""
    return (
        Deal.objects.filter(company=company)
        .select_related("stage", "portal_summary")
        .prefetch_related("quotes__status", "portal_lines", "portal_uploads")
    )


class RequestListView(BasePortalView):
    """GET/POST /requests — Запросы клиента."""

    def get(self, request):
        deals = list(_requests_queryset(request.portal_company).order_by("-created_at"))
        annotate_request_sources(deals)
        return Response(ClientRequestSerializer(deals, many=True).data)

    def post(self, request):
        serializer = ClientRequestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        data = serializer.validated_data
        deal = create_client_request(
            request.portal_company,
            request.portal_contact,
            summary=data["summary"],
            lines=data["lines"],
            attachments=data["attachments"],
        )
        created = _requests_queryset(request.portal_company).get(pk=deal.pk)
        return Response(ClientRequestSerializer(created).data, status=status.HTTP_201_CREATED)


class RequestDetailView(BasePortalView):
    """GET /requests/{id} — Детали запроса клиента (Q-16)."""

    def get(self, request, pk):
        deal = _requests_queryset(request.portal_company).filter(pk=pk).first()
        if not deal:
            raise Http404
        return Response(ClientRequestSerializer(deal).data)


# ── 4. Quotes ───────────────────────────────────────────────────────────────


def _client_quotes(company):
    """КП компании, которые видит клиент: только отправленные и решённые (`CLIENT_QUOTE_STATUSES`) с публичной ссылкой.

    Всё, что до отправки (черновик, проверка ВЭД, согласование, «готово к отправке»), — 404 (FIX-22, P-3): у такого КП
    нет `public_url`, а контракт требует его для каждого КП. Ссылка рождается вместе со статусом `SENT`
    (`QuoteLifecycleService.send_to_client`); запись без неё — аномалия данных, клиенту её не показываем.
    """
    return Quote.objects.filter(client_quotes_q(), deal__company=company).select_related(
        "status", "quote_currency", "deal"
    )


def _quote_or_404(request, pk):
    quote = _client_quotes(request.portal_company).filter(pk=pk).first()
    if not quote:
        raise Http404
    return quote


def _assert_quote_awaits_decision(quote) -> None:
    """Решать можно только КП в ожидании ответа: уже принятое или отклонённое — 409 `QUOTE_FINALIZED`, срок вышел — 409 `QUOTE_EXPIRED`."""
    if quote.status.code == _EXPIRED_STATUS_CODE:
        raise PortalConflict("QUOTE_EXPIRED")  # статус поставила ночная задача `crm.expire_stale_quotes`
    if quote.status.code != QuoteStatusCode.SENT:
        raise PortalConflict("QUOTE_FINALIZED")
    if quote.valid_until and quote.valid_until < timezone.localdate():
        raise PortalConflict("QUOTE_EXPIRED")


def _quote_response(request, pk) -> Response:
    return Response(QuoteSerializer(_quote_or_404(request, pk)).data)


class QuoteListView(BasePortalView):
    """GET /quotes — Список КП для клиента."""

    def get(self, request):
        quotes = _client_quotes(request.portal_company).order_by("-created_at")
        return Response(QuoteListItemSerializer(quotes, many=True).data)


class QuoteDetailView(BasePortalView):
    """GET /quotes/{id} — Детали КП с позициями."""

    def get(self, request, pk):
        quote = _quote_or_404(request, pk)

        # Отмечаем первый просмотр
        if quote.first_viewed_at is None:
            quote.first_viewed_at = timezone.now()
            quote.save(update_fields=["first_viewed_at"])

        return Response(QuoteSerializer(quote).data)


class QuoteRequestCodeView(BasePortalView):
    """POST /quotes/{id}/request-code — Код акцепта контакту сессии (Telegram или e-mail)."""

    permission_classes = [IsPortalAuthenticated, CanAct]
    # Общий потолок `portal_accept` на запрос кода и на акцепт (контракт): перебор и рассылка бьют в одно ведро.
    throttle_classes = [PortalSessionRateThrottle, PortalAcceptRateThrottle]

    def post(self, request, pk):
        quote = _quote_or_404(request, pk)
        _assert_quote_awaits_decision(quote)
        try:
            sent = request_acceptance_code(
                quote, request.portal_contact, request_ip=request.META.get("REMOTE_ADDR", "")
            )
        except ContactChannelRequired:
            raise PortalValidationError("CONTACT_CHANNEL_REQUIRED")
        return Response(AcceptanceCodeSentSerializer(sent).data, status=status.HTTP_202_ACCEPTED)


class QuoteAcceptView(BasePortalView):
    """POST /quotes/{id}/accept — Акцепт КП по коду из `request-code`."""

    permission_classes = [IsPortalAuthenticated, CanAct]
    # Жёсткий потолок попыток кода поверх общего лимита сессии (FIX-15).
    throttle_classes = [PortalSessionRateThrottle, PortalAcceptRateThrottle]

    def post(self, request, pk):
        serializer = QuoteAcceptSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        code = serializer.validated_data["code"].strip()

        quote = _quote_or_404(request, pk)
        _assert_quote_awaits_decision(quote)

        # Код акцепта — одноразовый, с TTL и лимитом попыток; погашение и акцепт — одна транзакция
        # (crm.services.public_page, общий путь с публичной страницей КП). Мастер-кода нет (FIX-02).
        accepted, error = verify_code_and_accept(
            quote, code, request_ip=request.META.get("REMOTE_ADDR", ""), contact=request.portal_contact
        )
        if error == "QUOTE_ALREADY_DECIDED":
            raise PortalConflict("QUOTE_FINALIZED")  # успели решить из другой вкладки
        if error:
            raise PortalConflict("QUOTE_CODE_INVALID")
        return _quote_response(request, pk)


class QuoteRejectView(BasePortalView):
    """POST /quotes/{id}/reject — Отклонение КП с причиной."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        reason = _parse_reason(request.data)
        quote = _quote_or_404(request, pk)
        _assert_quote_awaits_decision(quote)

        try:
            perform_quote_rejection(
                quote.id,
                rejected_by_user=None,
                reason=reason,
                contact_email=request.portal_contact.email,
                request_ip=request.META.get("REMOTE_ADDR"),
                portal_contact=request.portal_contact,
            )
        except ValueError:
            # Жизненный цикл отказал: решили из другой вкладки между проверкой и вызовом либо сделку не удалось вернуть.
            quote.refresh_from_db()
            code = quote.status.code
            raise PortalConflict(
                "QUOTE_EXPIRED"
                if code == _EXPIRED_STATUS_CODE
                else "QUOTE_FINALIZED" if code != QuoteStatusCode.SENT else "CONFLICT"
            )
        return _quote_response(request, pk)


# ── 5. Contracts ────────────────────────────────────────────────────────────


def _client_contracts(company):
    """Договоры компании, которые видит клиент: на подписи и подписанные. Черновик и отменённый — 404 (FIX-22)."""
    return Contract.objects.filter(client_contracts_q(), deal__company=company).select_related("status", "deal")


class ContractListView(BasePortalView):
    """GET /contracts — Договоры клиента."""

    def get(self, request):
        contracts = _client_contracts(request.portal_company).order_by("-created_at")
        return Response(ContractSerializer(contracts, many=True).data)


class ContractSignView(BasePortalView):
    """POST /contracts/{id}/sign — Подписание договора клиентом (`sign_contract_by_client`)."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        contract = _client_contracts(request.portal_company).filter(pk=pk).first()
        if not contract:
            raise Http404

        # Подпись и переход статуса — только сервис ERP: двусторонняя подпись, аудит, закрытие сделки (P-5).
        _, error = sign_contract_by_client(contract.pk, portal_contact=request.portal_contact)
        if error == "CONTRACT_CLIENT_SIGN_NOT_ALLOWED":
            raise PortalConflict("CONTRACT_FINALIZED")
        if error:
            raise exceptions.PermissionDenied("FORBIDDEN")
        return Response(ContractSerializer(_client_contracts(request.portal_company).get(pk=pk)).data)


# ── 6. Invoices ─────────────────────────────────────────────────────────────


class InvoiceListView(BasePortalView):
    """GET /invoices — Счета клиента (выставленные и со сроком оплаты: контракт требует `due_date`)."""

    def get(self, request):
        invoices = (
            Invoice.objects.filter(client_invoices_q(), deal__company=request.portal_company)
            .select_related("status", "deal", "currency", "contract__quote")
            .order_by("-created_at")
        )
        return Response(InvoiceSerializer(invoices, many=True).data)


# ── 7. Acts ─────────────────────────────────────────────────────────────────


def _client_acts(company):
    """Акты компании, которые видит клиент (`client_acts_q`): черновик без причины и аннулированный — 404 (FIX-22)."""
    return Act.objects.filter(deal__company=company).filter(client_acts_q()).select_related("status", "deal", "invoice")


def _act_response(request, pk) -> Response:
    act = _client_acts(request.portal_company).get(pk=pk)
    return Response(ActSerializer(act).data)


class ActListView(BasePortalView):
    """GET /acts — Акты выполненных работ."""

    def get(self, request):
        acts = list(_client_acts(request.portal_company).order_by("-created_at"))
        annotate_scan_documents(acts)
        return Response(ActSerializer(acts, many=True).data)


def _act_or_404(request, pk):
    act = _client_acts(request.portal_company).filter(pk=pk).first()
    if not act:
        raise Http404
    return act


def _raise_act_error(error: str) -> None:
    if error == "ACT_SIGN_NOT_ALLOWED":
        raise PortalConflict("ACT_FINALIZED")
    raise exceptions.PermissionDenied("FORBIDDEN")


class ActAcceptView(BasePortalView):
    """POST /acts/{id}/accept — Приёмка акта заказчиком (`sign_act`), со сканом из `/uploads` или без."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        serializer = ActAcceptSerializer(data=request.data or {})
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        upload_id = serializer.validated_data.get("upload_id")

        act = _act_or_404(request, pk)
        if act.status.code != ActStatusCode.ISSUED:
            raise PortalConflict("ACT_FINALIZED")  # принят, возвращён или ждёт перевыпуска

        upload, scan = load_scan(request.portal_company, upload_id, act.deal) if upload_id else (None, None)
        with transaction.atomic():
            signed, error = sign_act(act.pk, None, scan, portal_contact=request.portal_contact)
            if error:
                _raise_act_error(error)
            if upload is not None:
                attach_scan_document(signed, upload)
        return _act_response(request, pk)


class ActReturnView(BasePortalView):
    """POST /acts/{id}/return — Возврат акта с замечанием (`reject_act`): ERP хранит возвращённый акт черновиком с причиной."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        reason = _parse_reason(request.data)
        act = _act_or_404(request, pk)
        if act.status.code != ActStatusCode.ISSUED:
            raise PortalConflict("ACT_FINALIZED")

        _, error = reject_act(act.pk, None, reason, portal_contact=request.portal_contact)
        if error:
            _raise_act_error(error)
        return _act_response(request, pk)


# ── 8. Deliveries ───────────────────────────────────────────────────────────


def _client_delivery_lines(company):
    return DeliveryLine.objects.filter(deal__company=company).select_related("deal")


class DeliveryListView(BasePortalView):
    """GET /deliveries — Строки поставки по сделкам клиента (проекция клиента: без поставщика и цен)."""

    def get(self, request):
        sync_company_delivery_lines(request.portal_company)
        lines = _client_delivery_lines(request.portal_company).order_by("-deal_id", "line_no")
        return Response(DeliveryLineSerializer(lines, many=True).data)


def _delivery_line_or_404(request, pk):
    # Ход склада мог измениться после последнего чтения списка — строка должна быть актуальной до решения клиента.
    sync_company_delivery_lines(request.portal_company)
    line = _client_delivery_lines(request.portal_company).filter(pk=pk).first()
    if not line:
        raise Http404
    return line


def _delivery_response(request, pk) -> Response:
    return Response(DeliveryLineSerializer(_client_delivery_lines(request.portal_company).get(pk=pk)).data)


def _raise_delivery_error(error: str) -> None:
    if error == "DELIVERY_LINE_NOT_ACCEPTABLE":
        raise PortalConflict("DELIVERY_LINE_NOT_ACCEPTABLE")
    if error == "REASON_REQUIRED":
        raise PortalValidationError("REASON_REQUIRED")
    raise exceptions.PermissionDenied("FORBIDDEN")


class DeliveryAcceptView(BasePortalView):
    """POST /deliveries/{id}/accept — Клиент принимает строку: `delivered` → `accepted`."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        line = _delivery_line_or_404(request, pk)
        _, error = accept_delivery_line(line.pk, request.portal_contact)
        if error:
            _raise_delivery_error(error)
        return _delivery_response(request, pk)


class DeliveryDisputeView(BasePortalView):
    """POST /deliveries/{id}/dispute — Замечание по строке: `delivered` → `disputed`, менеджеру сделки — задача."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        reason = _parse_reason(request.data)
        line = _delivery_line_or_404(request, pk)
        _, error = dispute_delivery_line(line.pk, request.portal_contact, reason)
        if error:
            _raise_delivery_error(error)
        return _delivery_response(request, pk)


# ── 9. Documents & Files ────────────────────────────────────────────────────


def _client_ip(request) -> str:
    return request.META.get("REMOTE_ADDR") or ""


def _contact_language(request) -> str:
    """Язык подписей документов — язык контакта, а не заголовок запроса: Cabinet говорит на языке клиента."""
    language = (getattr(request.portal_contact, "language", "") or "").lower()
    return language if language in supported_languages() else settings.LANGUAGE_CODE


class DocumentListView(BasePortalView):
    """GET /documents — Выпущенные документы компании клиента (FIX-23); `kind` и `deal_id` — фильтры."""

    def get(self, request):
        kind = request.query_params.get("kind")
        if kind is not None and kind not in portal_documents.DOCUMENT_KINDS:
            raise PortalValidationError("VALIDATION_ERROR")
        deal_id = request.query_params.get("deal_id")
        if deal_id is not None:
            try:
                deal_id = int(deal_id)
            except ValueError:
                raise PortalValidationError("VALIDATION_ERROR") from None
        with translation.override(_contact_language(request)):
            documents = portal_documents.client_documents(request.portal_company, kind=kind, deal_id=deal_id)
        return Response(PortalDocumentSerializer(documents, many=True).data)


class DocumentFileView(BasePortalView):
    """GET /documents/{id}/file — PDF выпущенного документа: поток (и запись аудита) либо 202 + `Retry-After`."""

    def get(self, request, pk):
        document = portal_documents.find_client_document(request.portal_company, pk)
        if document is None:
            raise Http404

        response = portal_documents.ready_file_response(document)
        if response is None and not portal_documents.renders_on_demand(document):
            raise Http404  # скан акта без файла: рисовать нечего, 202 был бы обещанием, которое не исполнится
        if response is None:
            # PDF ещё не отрисован (или потерян в хранилище): рендер идёт в очередь, клиент приходит позже.
            portal_documents.enqueue_render(document)
            return Response(
                {"detail": "DOCUMENT_PENDING"},
                status=status.HTTP_202_ACCEPTED,
                headers={"Retry-After": str(portal_documents.RETRY_AFTER_SECONDS)},
            )

        portal_documents.record_issue(
            document, contact=request.portal_contact, session=request.portal_session, ip=_client_ip(request)
        )
        return response


# ── 10. Uploads ─────────────────────────────────────────────────────────────


class UploadView(BasePortalView):
    """POST /uploads — Загрузка файлов клиентом (Q-14, multipart, <= 10MB)."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        file_obj = request.FILES.get("file")
        if not file_obj:
            raise PortalBadRequest("FILE_REQUIRED")

        # Лимит размера — по контракту 10 МБ, настройка `PORTAL_UPLOAD_MAX_BYTES`.
        if file_obj.size > settings.PORTAL_UPLOAD_MAX_BYTES:
            raise PortalValidationError("FILE_TOO_LARGE")

        upload = PortalUpload.objects.create(
            company=request.portal_company,
            uploaded_by=request.portal_contact,
            name=file_obj.name,
            file=file_obj,
            size_bytes=file_obj.size,
            content_type=getattr(file_obj, "content_type", "application/octet-stream"),
        )
        return Response(
            PortalUploadResponseSerializer(
                {
                    "upload_id": str(upload.upload_id),
                    "name": upload.name,
                    "mime_type": upload.content_type,
                    "size_bytes": upload.size_bytes,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )


# ── 11. Catalog (Published Layer) ───────────────────────────────────────────


class CatalogCategoriesView(BasePortalView):
    """GET /catalog/categories — Справочник категорий с количеством (Q-15)."""

    def get(self, request):
        from django.db.models import Count, Q

        from catalog.models import Category

        categories = (
            Category.objects.filter(is_active=True)
            .annotate(count=Count("products", filter=Q(products__status__code="PUBLISHED")))
            .filter(count__gt=0)
            .order_by("sort_order", "name")
        )
        items = [{"id": c.id, "name": c.name, "count": c.count} for c in categories]
        return Response(CatalogCategorySerializer(items, many=True).data)


class CatalogListView(BasePortalView):
    """GET /catalog — Опубликованный каталог товаров и услуг."""

    def get(self, request):
        qs = published_products()

        q = request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)

        category_id = request.query_params.get("category_id")
        if category_id:
            try:
                qs = qs.filter(category_id=int(category_id))
            except ValueError:
                pass

        total = qs.count()

        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except ValueError:
            page = 1
            page_size = 20

        start = (page - 1) * page_size
        products_page = qs[start : start + page_size]

        resp_data = {
            "items": project_many(products_page, mode="client", request=request),
            "page": page,
            "page_size": page_size,
            "total": total,
        }
        return Response(CatalogPageSerializer(resp_data).data)


class CatalogDetailView(BasePortalView):
    """GET /catalog/{id} — Карточка товара/услуги в опубликованном слое."""

    def get(self, request, pk):
        product = published_products().filter(pk=pk).first()
        if not product:
            raise Http404

        item_data = project(product, mode="client", request=request)
        return Response(CatalogItemSerializer(item_data).data)


# ── 12. Company & Team ──────────────────────────────────────────────────────


class CompanyView(BasePortalView):
    """GET/PUT /company — Профиль компании клиента."""

    def get(self, request):
        return Response(CompanySerializer(request.portal_company).data)

    def put(self, request):
        if not request.portal_contact.can_act:
            raise PortalConflict("FORBIDDEN")

        serializer = CompanyUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")

        data = serializer.validated_data
        company = request.portal_company

        # Название и ИНН клиента ведёт CRM (B3): правка из Cabinet отвергается, значение вернулось бы со следующим снимком.
        if changed_crm_owned_fields(company, data):
            raise PortalValidationError(REQUISITES_MANAGED_BY_CRM)

        if "name" in data and data["name"].strip():
            company.name = data["name"].strip()
        if "inn" in data:
            inn = data["inn"].strip()
            if inn and len(inn) != 9:
                raise PortalValidationError("INN_INVALID")
            company.inn = inn or None
        if "legal_address" in data:
            company.legal_address = data["legal_address"].strip()
        if "bank_details" in data:
            company.bank_details = data["bank_details"].strip()
        if "language" in data:
            company.language = data["language"]

        company.save()
        return Response(CompanySerializer(company).data)


class TeamListView(BasePortalView):
    """GET /team — Список участников команды клиента."""

    def get(self, request):
        contacts = Contact.objects.filter(active_contact_q(), company=request.portal_company).order_by(
            "-is_primary", "name"
        )
        return Response(TeamMemberSerializer(contacts, many=True).data)


class TeamInviteView(BasePortalView):
    """POST /team/invite — Приглашение коллеги в кабинет (доставляется письмом; `telegram` — 422 `INVALID_CHANNEL`)."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request):
        serializer = TeamInviteSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        contact = invite_team_member(request.portal_company, request.portal_contact, serializer.validated_data)
        return Response(TeamMemberSerializer(contact).data, status=status.HTTP_201_CREATED)
