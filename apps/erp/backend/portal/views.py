"""Portal API Views (Cabinet → ERP, M2-ERP-01).

Реализация всех эндпоинтов по packages/contracts/openapi/erp-portal.yaml и CONTRACTS §4.
Все ответы отфильтрованы по компании текущей сессии (`request.portal_company`).
Попытка доступа к объекту другой компании возвращает 404 {"detail": "NOT_FOUND"}.
Действия мутации требуют CanAct (can_act=True), иначе 403 {"detail": "FORBIDDEN"}.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse
from django.utils import timezone, translation
from integration.services.requisites import REQUISITES_MANAGED_BY_CRM, changed_crm_owned_fields
from parties.models import (
    CompanyRelationship,
    Contact,
    PartnerApplication,
    PartnerApplicationSource,
    PartnerApplicationStatus,
    RelationshipRole,
    RelationshipStatus,
    active_contact_q,
)
from portal.authentication import PortalAuthentication
from portal.exceptions import PortalBadRequest, PortalConflict, PortalValidationError, portal_exception_handler
from portal.models import MagicLinkToken, PortalDocumentVerification, PortalSession, PortalUpload
from portal.permissions import ANY_MODULE, CanAct, HasPortalModule, IsPortalAuthenticated
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
    DocumentVerificationSerializer,
    InvoiceSerializer,
    LoginCodeSerializer,
    MagicLinkRequestSerializer,
    MagicLinkTokenSerializer,
    MeSerializer,
    PartnerApplicationClientCreateSerializer,
    PartnerApplicationPublicCreateSerializer,
    PartnerApplicationSerializer,
    PaymentProofCreateSerializer,
    PaymentProofSerializer,
    PortalDocumentSerializer,
    PortalSessionItemSerializer,
    PortalUploadResponseSerializer,
    QuoteAcceptSerializer,
    QuoteCommentCreateSerializer,
    QuoteCommentSerializer,
    QuoteListItemSerializer,
    QuoteSerializer,
    ReasonSerializer,
    TeamInviteSerializer,
    TeamMemberSerializer,
    TeamMemberUpdateSerializer,
    TelegramAuthSerializer,
)
from portal.services import catalog_documents
from portal.services import documents as portal_documents
from portal.services import notices
from portal.services.acceptance import ContactChannelRequired, request_acceptance_code
from portal.services.access import company_access
from portal.services.act_scan import annotate_scan_documents, attach_scan_document, load_scan
from portal.services.client_feedback import add_quote_comment, submit_payment_proof
from portal.services.invitation import invite_team_member
from portal.services.login_code import exchange_login_code
from portal.services.magic_link import exchange_magic_link, request_magic_link
from portal.services.messages import unread_count
from portal.services.requests import create_client_request
from portal.services.telegram_auth import authenticate_telegram_user
from portal.throttles import (
    PortalAcceptRateThrottle,
    PortalLoginRateThrottle,
    PortalPartnerAppRateThrottle,
    PortalSessionRateThrottle,
    PortalVerifyRateThrottle,
)
from rest_framework import exceptions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from sales.models import DeliveryLine
from sales.services.delivery_lines import accept_delivery_line, dispute_delivery_line, sync_company_delivery_lines

from catalog.published import project, project_many, published_products
from core.i18n import supported_languages
from core.models import Country
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


def _me_data(session, auth_method: str | None = None, access: tuple[list[str], list[str]] | None = None) -> dict:
    """Тело `Me`: контакт, компания, права, роли и модули кабинета (общее для входа и `GET /me`)."""
    roles, modules = company_access(session.company_id) if access is None else access
    return {
        "contact": TeamMemberSerializer(session.contact).data,
        "company": CompanySerializer(session.company).data,
        "can_act": session.contact.can_act,
        "is_admin": session.contact.is_admin,
        "auth_method": auth_method or session.auth_method,
        "notifications_unread": notices.unread_count(session.contact, session.company, modules),
        "roles": roles,
        "modules": modules,
        # Непрочитанные ответы менеджера в чате кабинета (CHAT-1): бейдж «Сообщения»; без модуля — 0.
        "unread": unread_count(session.company_id, session.contact_id) if "messages" in modules else 0,
    }


class BasePortalView(APIView):
    """Базовый класс для портальных эндпоинтов с аутентификацией."""

    authentication_classes = [PortalAuthentication]
    #: Модуль, которому открыт эндпоинт (ADR-0022): каждая вьюха называет свой (`required_module`), без него — закрыта;
    #: сессия без модуля — 403 `MODULE_REQUIRED`. Порядок важен: модуль проверяется раньше права действовать, чтобы
    #: сессия без модуля не узнавала про `FORBIDDEN`.
    permission_classes = [IsPortalAuthenticated, HasPortalModule, CanAct]
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

        res = Response(MeSerializer(_me_data(session, "telegram")).data, status=status.HTTP_200_OK)
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
        sent = request_magic_link(email)
        if not sent:
            return Response(
                {"status": "not_registered", "sent": False, "email": email},
                status=status.HTTP_200_OK,
            )
        return Response({"status": "ok", "sent": True, "email": email}, status=status.HTTP_200_OK)


def _exchange_magic_token(request, token: str) -> Response:
    """Обмен токена ссылки входа на сессию (`POST /auth/magic`)."""
    session, session_token = exchange_magic_link(
        token,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
    return _session_response(session, session_token)


def _session_response(session, session_token: str) -> Response:
    """Ответ входа по письму (ссылка или код): `Me` и cookie сессии."""
    res = Response(MeSerializer(_me_data(session, "magic_link")).data, status=status.HTTP_200_OK)
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


class LoginCodeExchangeView(APIView):
    """POST /auth/code {email, code} — вход по 6-значному коду из письма входа или приглашения (B-MAIL-1).

    Неверный, устаревший код и неизвестный адрес — 422 `LOGIN_CODE_INVALID`; 5 неверных подряд — 429 `LOGIN_CODE_LOCKED`.
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [PortalLoginRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def post(self, request):
        serializer = LoginCodeSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        session, session_token = exchange_login_code(
            serializer.validated_data["email"],
            serializer.validated_data["code"],
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        return _session_response(session, session_token)


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


class PortalSessionsView(APIView):
    """GET /auth/sessions — Список активных сессий текущего контакта (J2)."""

    authentication_classes = [PortalAuthentication]
    permission_classes = [IsPortalAuthenticated]
    throttle_classes = [PortalSessionRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def get(self, request):
        sessions = PortalSession.objects.filter(
            contact=request.portal_contact,
            expires_at__gt=timezone.now(),
        ).order_by("-last_used_at", "-created_at")
        serializer = PortalSessionItemSerializer(
            sessions,
            many=True,
            context={"current_session": request.portal_session},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class PortalSessionsRevokeOthersView(APIView):
    """POST /auth/sessions/revoke-others — Завершить все остальные сессии текущего контакта (J2)."""

    authentication_classes = [PortalAuthentication]
    permission_classes = [IsPortalAuthenticated]
    throttle_classes = [PortalSessionRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def post(self, request):
        revoked_count, _ = (
            PortalSession.objects.filter(
                contact=request.portal_contact,
                expires_at__gt=timezone.now(),
            )
            .exclude(pk=request.portal_session.pk)
            .delete()
        )
        return Response({"revoked_count": revoked_count}, status=status.HTTP_200_OK)


class DocumentVerificationView(APIView):
    """GET /verify/{code} — Публичная проверка официального документа по коду (ADR-0024 §6, SIGN-VERIFY-1)."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [PortalVerifyRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def get(self, request, code: str):
        cleaned_code = code.strip()
        verification = PortalDocumentVerification.objects.filter(code=cleaned_code).first()
        if not verification:
            raise exceptions.NotFound(detail="NOT_FOUND")
        return Response(DocumentVerificationSerializer(verification).data, status=status.HTTP_200_OK)


class PublicPartnerApplicationView(APIView):
    """POST /auth/partner-application — Публичная подача заявки «Стать партнёром» (ADR-0022, DECISIONS 2026-11-05)."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [PortalPartnerAppRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def post(self, request):
        serializer = PartnerApplicationPublicCreateSerializer(data=request.data)
        if not serializer.is_valid():
            if "consent" in serializer.errors:
                raise PortalBadRequest("CONSENT_REQUIRED")
            if "website" in serializer.errors:
                raise PortalBadRequest("HONEYPOT_DETECTED")
            raise PortalValidationError("VALIDATION_ERROR")
        data = serializer.validated_data
        country_code = (data.get("country") or "UZ").strip().upper()
        country = Country.objects.filter(code__iexact=country_code).first()
        inn = (data.get("inn") or "").strip()
        reg_num = (data.get("registration_number") or "").strip()
        if country_code != "UZ" and not reg_num and inn:
            reg_num = inn
            inn = ""

        app = PartnerApplication.objects.create(
            source=PartnerApplicationSource.PUBLIC,
            country=country,
            company_name=data["company_name"].strip(),
            inn=inn,
            registration_number=reg_num,
            kind=data.get("kind") or "supplier",
            categories_description=data["categories_description"].strip(),
            contact_name=data["contact_name"].strip(),
            email=data["email"].strip().lower(),
            phone=(data.get("phone") or "").strip(),
            language=data.get("language") or "ru",
            consent=True,
            status=PartnerApplicationStatus.SUBMITTED,
        )
        return Response({"id": app.id, "status": app.status}, status=status.HTTP_201_CREATED)


class CountriesView(APIView):
    """GET /countries — Справочник стран с метаданными телефонных кодов и налоговых номеров (COUNTRY-MASK-1)."""

    authentication_classes = []
    permission_classes = []

    def get_exception_handler(self):
        return portal_exception_handler

    def get(self, request):
        from portal.services.countries import list_portal_countries

        return Response(list_portal_countries(), status=status.HTTP_200_OK)


# ── 2. Me ───────────────────────────────────────────────────────────────────


class MeView(BasePortalView):
    """GET /me — Текущий профиль сессии (контакт, компания, права, роли и модули кабинета)."""

    required_module = ANY_MODULE  # профиль нужен любой сессии: по ролям и модулям Cabinet строит меню

    def get(self, request):
        return Response(
            MeSerializer(_me_data(request.portal_session, access=(request.portal_roles, request.portal_modules))).data
        )


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

    required_module = "catalog_requests"

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

    required_module = "catalog_requests"

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

    required_module = "quotes"

    def get(self, request):
        quotes = _client_quotes(request.portal_company).order_by("-created_at")
        return Response(QuoteListItemSerializer(quotes, many=True).data)


class QuoteDetailView(BasePortalView):
    """GET /quotes/{id} — Детали КП с позициями."""

    required_module = "quotes"

    def get(self, request, pk):
        quote = _quote_or_404(request, pk)

        # Отмечаем первый просмотр
        if quote.first_viewed_at is None:
            quote.first_viewed_at = timezone.now()
            quote.save(update_fields=["first_viewed_at"])

        return Response(QuoteSerializer(quote).data)


class QuoteRequestCodeView(BasePortalView):
    """POST /quotes/{id}/request-code — Код акцепта контакту сессии (Telegram или e-mail)."""

    required_module = "quotes"

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

    required_module = "quotes"

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

    required_module = "quotes"

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


class QuoteCommentView(BasePortalView):
    """POST /quotes/{id}/comments — Комментарий клиента к КП, пока оно ждёт решения (B-CABFIX-1)."""

    required_module = "quotes"

    def post(self, request, pk):
        serializer = QuoteCommentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        text = serializer.validated_data["text"].strip()
        if not text:
            raise PortalValidationError("TEXT_REQUIRED")
        quote = _quote_or_404(request, pk)
        _assert_quote_awaits_decision(quote)
        comment = add_quote_comment(quote, request.portal_contact, text)
        return Response(QuoteCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


# ── 5. Contracts ────────────────────────────────────────────────────────────


def _client_contracts(company):
    """Договоры компании, которые видит клиент: на подписи и подписанные. Черновик и отменённый — 404 (FIX-22)."""
    return Contract.objects.filter(client_contracts_q(), deal__company=company).select_related("status", "deal")


class ContractListView(BasePortalView):
    """GET /contracts — Договоры клиента."""

    required_module = "contracts"

    def get(self, request):
        contracts = _client_contracts(request.portal_company).order_by("-created_at")
        return Response(ContractSerializer(contracts, many=True).data)


class ContractSignView(BasePortalView):
    """POST /contracts/{id}/sign — Подписание договора клиентом (`sign_contract_by_client`)."""

    required_module = "contracts"

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


def _client_invoices(company):
    return Invoice.objects.filter(client_invoices_q(), deal__company=company).select_related(
        "status", "deal", "currency", "contract__quote"
    )


class InvoiceListView(BasePortalView):
    """GET /invoices — Счета клиента (выставленные и со сроком оплаты: контракт требует `due_date`)."""

    required_module = "invoices"

    def get(self, request):
        invoices = _client_invoices(request.portal_company).prefetch_related("confirmations").order_by("-created_at")
        return Response(InvoiceSerializer(invoices, many=True).data)


class InvoiceProofView(BasePortalView):
    """POST /invoices/{id}/proofs — «Я оплатил»: платёжное поручение из `/uploads` к счёту (B-CABFIX-1).

    Платёжка ложится в ту же `PaymentConfirmation`, что у менеджера (источник — кабинет), и ждёт подтверждения оплаты
    в «Счетах и оплатах». Чужой или невидимый клиенту счёт — 404, оплаченный или отменённый — 409 `INVOICE_NOT_OPEN`.
    """

    required_module = "invoices"

    def post(self, request, pk):
        serializer = PaymentProofCreateSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        data = serializer.validated_data
        invoice = _client_invoices(request.portal_company).filter(pk=pk).first()
        if invoice is None:
            raise Http404
        proof = submit_payment_proof(
            invoice,
            request.portal_contact,
            upload_id=data["upload_id"],
            paid_on=data.get("paid_on"),
            amount=data.get("amount"),
            comment=data.get("comment") or "",
        )
        currency = invoice.currency.code if invoice.currency_id else None
        return Response(
            PaymentProofSerializer(proof, context={"currency": currency}).data, status=status.HTTP_201_CREATED
        )


# ── 7. Acts ─────────────────────────────────────────────────────────────────


def _client_acts(company):
    """Акты компании, которые видит клиент (`client_acts_q`): черновик без причины и аннулированный — 404 (FIX-22)."""
    return Act.objects.filter(deal__company=company).filter(client_acts_q()).select_related("status", "deal", "invoice")


def _act_response(request, pk) -> Response:
    act = _client_acts(request.portal_company).get(pk=pk)
    return Response(ActSerializer(act).data)


class ActListView(BasePortalView):
    """GET /acts — Акты выполненных работ."""

    required_module = "acts"

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

    required_module = "acts"

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

    required_module = "acts"

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

    required_module = "deliveries"

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

    required_module = "deliveries"

    def post(self, request, pk):
        line = _delivery_line_or_404(request, pk)
        _, error = accept_delivery_line(line.pk, request.portal_contact)
        if error:
            _raise_delivery_error(error)
        return _delivery_response(request, pk)


class DeliveryDisputeView(BasePortalView):
    """POST /deliveries/{id}/dispute — Замечание по строке: `delivered` → `disputed`, менеджеру сделки — задача."""

    required_module = "deliveries"

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

    required_module = "documents"

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

    required_module = "documents"

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

    required_module = "catalog_requests"

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

    required_module = "catalog_requests"

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

    required_module = "catalog_requests"

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

    required_module = "catalog_requests"

    def get(self, request, pk):
        product = published_products().filter(pk=pk).first()
        if not product:
            raise Http404

        item_data = project(product, mode="client", request=request, with_documents=True)
        return Response(CatalogItemSerializer(item_data).data)


class CatalogDocumentFileView(BasePortalView):
    """GET /catalog/{id}/documents/{doc_id}/file — файл документа карточки: поток и запись аудита (CAT-CARD-2)."""

    required_module = "catalog_requests"

    def get(self, request, pk, doc_id):
        document = catalog_documents.find_client_document(pk, doc_id)
        if document is None:
            raise Http404
        response = catalog_documents.file_response(document)
        if response is None:
            raise Http404  # файл потерян в хранилище: клиенту — то же 404, причины не различаются
        catalog_documents.record_issue(
            document, contact=request.portal_contact, session=request.portal_session, ip=_client_ip(request)
        )
        return response


# ── 12. Company & Team ──────────────────────────────────────────────────────


class CompanyView(BasePortalView):
    """GET/PUT /company — Профиль компании клиента."""

    required_module = "company"

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
        if "country_code" in data:
            code = data["country_code"].strip().upper()
            if code:
                country = Country.objects.filter(code=code).first()
                if country:
                    company.country = country
        if "registration_number" in data:
            company.registration_number = data["registration_number"].strip()
        if "inn" in data:
            inn = data["inn"].strip()
            is_uz = not company.country or company.country.code == "UZ"
            if is_uz and inn and len(inn) != 9:
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


class CompanyPartnerApplicationView(BasePortalView):
    """GET/POST /company/partner-application — Заявка действующего клиента на получение роли партнёра."""

    required_module = "company"

    def get(self, request):
        already_partner = "partner" in getattr(request, "portal_roles", []) or (
            CompanyRelationship.objects.filter(
                company=request.portal_company, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE
            ).exists()
        )
        app = PartnerApplication.objects.filter(company=request.portal_company).order_by("-created_at").first()
        if not app and getattr(request, "portal_contact", None) and request.portal_contact.email:
            app = (
                PartnerApplication.objects.filter(email__iexact=request.portal_contact.email)
                .order_by("-created_at")
                .first()
            )
        return Response(
            {
                "already_partner": bool(already_partner),
                "has_application": app is not None
                and app.status
                in (
                    PartnerApplicationStatus.SUBMITTED,
                    PartnerApplicationStatus.CONTRACT_SENT,
                    PartnerApplicationStatus.CANDIDATE_AGREED,
                ),
                "application": PartnerApplicationSerializer(app).data if app else None,
            }
        )

    def post(self, request):
        if not getattr(request.portal_contact, "can_act", False):
            raise exceptions.PermissionDenied(detail="FORBIDDEN")
        already_partner = "partner" in getattr(request, "portal_roles", []) or (
            CompanyRelationship.objects.filter(
                company=request.portal_company, role=RelationshipRole.PARTNER, status=RelationshipStatus.ACTIVE
            ).exists()
        )
        if already_partner:
            raise PortalConflict("ALREADY_PARTNER")

        existing = PartnerApplication.objects.filter(
            company=request.portal_company,
            status__in=[
                PartnerApplicationStatus.SUBMITTED,
                PartnerApplicationStatus.CONTRACT_SENT,
                PartnerApplicationStatus.CANDIDATE_AGREED,
            ],
        ).first()
        if existing:
            raise PortalConflict("APPLICATION_EXISTS")

        serializer = PartnerApplicationClientCreateSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        data = serializer.validated_data
        contact = request.portal_contact
        company = request.portal_company
        app = PartnerApplication.objects.create(
            source=PartnerApplicationSource.CLIENT_CABINET,
            company=company,
            applicant_contact=contact,
            company_name=company.name,
            country=company.country,
            inn=company.inn or "",
            registration_number=company.registration_number or "",
            kind=data.get("kind") or "supplier",
            categories_description=data["categories_description"].strip(),
            contact_name=contact.name if contact else "",
            email=contact.email if contact else "",
            phone=contact.phone if contact else "",
            language=contact.language if contact else "ru",
            consent=True,
            status=PartnerApplicationStatus.SUBMITTED,
        )
        return Response(PartnerApplicationSerializer(app).data, status=status.HTTP_201_CREATED)


class CompanyPartnerContractPdfView(BasePortalView):
    """GET /company/partner-application/contract-pdf — Скачать проект или подписанный партнёрский договор."""

    required_module = "company"

    def get(self, request):
        app = PartnerApplication.objects.filter(company=request.portal_company).order_by("-created_at").first()
        if not app and getattr(request, "portal_contact", None) and request.portal_contact.email:
            app = (
                PartnerApplication.objects.filter(email__iexact=request.portal_contact.email)
                .order_by("-created_at")
                .first()
            )

        if not app:
            raise exceptions.NotFound("NOT_FOUND")

        from django.core.files.base import ContentFile
        from portal.services.partner_contract import render_partner_contract_pdf

        if not app.contract_pdf:
            is_draft = app.status != PartnerApplicationStatus.APPROVED
            pdf_bytes = render_partner_contract_pdf(app, draft=is_draft)
            filename = f"Partner_Contract_{app.contract_number or app.pk}_{'draft' if is_draft else 'signed'}.pdf"
            app.contract_pdf.save(filename, ContentFile(pdf_bytes), save=True)
        else:
            try:
                pdf_bytes = app.contract_pdf.read()
            except Exception:
                is_draft = app.status != PartnerApplicationStatus.APPROVED
                pdf_bytes = render_partner_contract_pdf(app, draft=is_draft)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        filename = f"Partner_Contract_{app.contract_number or app.pk}.pdf"
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response


class CompanyPartnerApplicationAgreeView(BasePortalView):
    """POST /company/partner-application/agree — Согласование проекта договора кандидатом."""

    required_module = "company"

    def post(self, request):
        if not getattr(request.portal_contact, "can_act", False):
            raise exceptions.PermissionDenied(detail="FORBIDDEN")

        app = (
            PartnerApplication.objects.filter(
                company=request.portal_company,
                status=PartnerApplicationStatus.CONTRACT_SENT,
            )
            .order_by("-created_at")
            .first()
        )
        if not app and getattr(request, "portal_contact", None) and request.portal_contact.email:
            app = (
                PartnerApplication.objects.filter(
                    email__iexact=request.portal_contact.email,
                    status=PartnerApplicationStatus.CONTRACT_SENT,
                )
                .order_by("-created_at")
                .first()
            )

        if not app:
            raise PortalBadRequest("NOT_IN_CONTRACT_SENT_STATUS")

        notes = (request.data.get("notes") or "").strip()
        app.status = PartnerApplicationStatus.CANDIDATE_AGREED
        app.candidate_agreed_at = timezone.now()
        if notes:
            app.candidate_notes = notes

        # Перерендерим проект договора с отметкой о согласовании кандидатом
        from django.core.files.base import ContentFile
        from portal.services.partner_contract import render_partner_contract_pdf

        pdf_bytes = render_partner_contract_pdf(app, draft=True)
        filename = f"Partner_Contract_{app.contract_number or app.pk}_agreed.pdf"
        app.contract_pdf.save(filename, ContentFile(pdf_bytes), save=False)
        app.save()

        return Response(PartnerApplicationSerializer(app).data, status=status.HTTP_200_OK)


class TeamListView(BasePortalView):
    """GET /team — Список участников команды клиента."""

    required_module = "team"

    def get(self, request):
        contacts = Contact.objects.filter(active_contact_q(), company=request.portal_company).order_by(
            "-is_primary", "name"
        )
        return Response(TeamMemberSerializer(contacts, many=True).data)


class TeamInviteView(BasePortalView):
    """POST /team/invite — Приглашение коллеги в кабинет (доставляется письмом; `telegram` — 422 `INVALID_CHANNEL`)."""

    required_module = "team"

    def post(self, request):
        serializer = TeamInviteSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")
        contact = invite_team_member(request.portal_company, request.portal_contact, serializer.validated_data)
        return Response(TeamMemberSerializer(contact).data, status=status.HTTP_201_CREATED)


class TeamMemberDetailView(BasePortalView):
    """PATCH /team/{id} — Обновление прав коллеги (J2, только администратор компании)."""

    required_module = "team"

    def patch(self, request, pk: int):
        if not getattr(request.portal_contact, "is_admin", False):
            raise exceptions.PermissionDenied("ADMIN_REQUIRED")

        target = Contact.objects.filter(
            active_contact_q(),
            pk=pk,
            company=request.portal_company,
        ).first()
        if target is None:
            raise Http404

        serializer = TeamMemberUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")

        validated = serializer.validated_data

        # Защита основного контакта: статус администратора и право действовать нельзя снять
        if target.is_primary:
            if "is_admin" in validated and not validated["is_admin"]:
                raise PortalValidationError("CANNOT_MODIFY_PRIMARY_CONTACT")
            if "can_act" in validated and not validated["can_act"]:
                raise PortalValidationError("CANNOT_MODIFY_PRIMARY_CONTACT")

        # Защита последнего администратора: нельзя снять статус администратора с единственного админа компании
        if "is_admin" in validated and not validated["is_admin"] and target.is_admin:
            has_other_admin = (
                Contact.objects.filter(
                    active_contact_q(),
                    company=request.portal_company,
                    is_admin=True,
                )
                .exclude(pk=target.pk)
                .exists()
            )
            if not has_other_admin:
                raise PortalValidationError("LAST_ADMIN_CANNOT_BE_REMOVED")

        fields_to_update = []
        if "can_act" in validated:
            target.can_act = validated["can_act"]
            fields_to_update.append("can_act")
        if "is_admin" in validated:
            target.is_admin = validated["is_admin"]
            fields_to_update.append("is_admin")

        if fields_to_update:
            target.save(update_fields=fields_to_update)

        return Response(TeamMemberSerializer(target).data, status=status.HTTP_200_OK)


class TeamMemberDeactivateView(BasePortalView):
    """POST /team/{id}/deactivate — Отключение коллеги и завершение всех его сессий (J2, только администратор)."""

    required_module = "team"

    def post(self, request, pk: int):
        if not getattr(request.portal_contact, "is_admin", False):
            raise exceptions.PermissionDenied("ADMIN_REQUIRED")

        target = Contact.objects.filter(
            active_contact_q(),
            pk=pk,
            company=request.portal_company,
        ).first()
        if target is None:
            raise Http404

        if target.pk == request.portal_contact.pk:
            raise PortalValidationError("CANNOT_DEACTIVATE_SELF")

        if target.is_primary:
            raise PortalValidationError("CANNOT_MODIFY_PRIMARY_CONTACT")

        if target.is_admin:
            has_other_admin = (
                Contact.objects.filter(
                    active_contact_q(),
                    company=request.portal_company,
                    is_admin=True,
                )
                .exclude(pk=target.pk)
                .exists()
            )
            if not has_other_admin:
                raise PortalValidationError("LAST_ADMIN_CANNOT_BE_REMOVED")

        target.archived_at = timezone.now()
        target.is_admin = False
        target.can_act = False
        target.save(update_fields=["archived_at", "is_admin", "can_act"])

        PortalSession.objects.filter(contact=target).delete()
        MagicLinkToken.objects.filter(contact=target).delete()

        return Response({"ok": True, "deactivated_contact_id": target.pk}, status=status.HTTP_200_OK)
