"""Portal API Views (Cabinet → ERP, M2-ERP-01).

Реализация всех эндпоинтов по packages/contracts/openapi/erp-portal.yaml и CONTRACTS §4.
Все ответы отфильтрованы по компании текущей сессии (`request.portal_company`).
Попытка доступа к объекту другой компании возвращает 404 {"detail": "NOT_FOUND"}.
Действия мутации требуют CanAct (can_act=True), иначе 403 {"detail": "FORBIDDEN"}.
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404
from django.utils import timezone
from parties.models import Contact
from portal.authentication import PortalAuthentication
from portal.exceptions import PortalBadRequest, PortalConflict, PortalValidationError, portal_exception_handler
from portal.models import PortalRequestLine, PortalRequestSummary, PortalUpload
from portal.permissions import CanAct, IsPortalAuthenticated
from portal.projections import annotate_request_sources, delivery_lines
from portal.serializers import (
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
from portal.services.invitation import invite_contact_to_portal
from portal.services.magic_link import exchange_magic_link, request_magic_link
from portal.services.telegram_auth import authenticate_telegram_user
from portal.throttles import PortalAcceptRateThrottle, PortalLoginRateThrottle, PortalSessionRateThrottle
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.published import project, project_many, published_products
from crm.constants import DealStageCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import Act, ActivityLog, Contract, Deal, DealStage, Fulfillment, GeneratedDocument, Invoice, Quote
from crm.services.deals import transition_deal_stage
from crm.services.public_page import verify_code_and_accept
from sourcing.models import Attachment

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
            from rest_framework import exceptions

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
    """Обмен токена ссылки входа на сессию — общий для `POST /auth/magic` и устаревшего `GET /auth/magic/{token}`."""
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


class MagicLinkExchangeView(APIView):
    """GET /auth/magic/{token} — устарело (токен в пути попадает в журналы), остаётся до FIX-24; см. `POST /auth/magic`."""

    authentication_classes = []
    permission_classes = []
    throttle_classes = [PortalLoginRateThrottle]

    def get_exception_handler(self):
        return portal_exception_handler

    def get(self, request, token):
        return _exchange_magic_token(request, token)

    def post(self, request, token):
        return self.get(request, token)


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


def _short_title(summary: str) -> str:
    """Название сделки из сути запроса: одна строка, не длиннее поля `Deal.title`."""
    title = " ".join(summary.split())
    max_length = Deal._meta.get_field("title").max_length
    return title if len(title) <= max_length else title[: max_length - 1].rstrip() + "…"


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
        summary = data["summary"]
        lines = data.get("lines", [])
        attachments = data.get("attachments", [])

        draft_stage = DealStage.objects.filter(code=DealStageCode.DRAFT).first()

        with transaction.atomic():
            deal = Deal.objects.create(
                company=request.portal_company,
                contact=request.portal_contact,
                title=_short_title(summary),
                stage=draft_stage,
                notes="Запрос создан клиентом из Cabinet",
            )
            # Название сделки — 255 знаков, суть запроса по контракту — до 5000: полный текст лежит отдельно
            PortalRequestSummary.objects.create(deal=deal, text=summary)
            # Привязка строк
            for idx, line in enumerate(lines, start=1):
                PortalRequestLine.objects.create(
                    deal=deal,
                    text=line["text"],
                    quantity=Decimal(line.get("quantity") or "1"),
                    unit=line.get("unit") or "шт",
                    sort_order=idx,
                )

            # Привязка вложений из PortalUpload (Q-14)
            for att_ref in attachments:
                upload_id = att_ref.get("upload_id")
                upload = PortalUpload.objects.filter(
                    upload_id=upload_id,
                    company=request.portal_company,
                ).first()
                if upload:
                    upload.deal = deal
                    upload.save(update_fields=["deal"])
                    Attachment.objects.create(
                        deal=deal,
                        file=upload.file,
                        original_filename=upload.name,
                        kind="SOURCE",
                    )

            # Логируем аудит-событие
            ActivityLog.objects.create(
                deal=deal,
                action="Создан запрос",
                event_code="deal.created",
                detail=f"Клиент создал запрос из Cabinet: {summary}",
                event_params={"source": "cabinet", "contact_id": request.portal_contact.id},
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
    """КП компании, которые видит портал. Какие именно — правило FIX-22; сейчас всё, кроме черновиков."""
    return (
        Quote.objects.filter(deal__company=company)
        .exclude(status__code=QuoteStatusCode.DRAFT)
        .select_related("status", "quote_currency", "deal")
    )


class QuoteListView(BasePortalView):
    """GET /quotes — Список КП для клиента."""

    def get(self, request):
        quotes = _client_quotes(request.portal_company).order_by("-created_at")
        return Response(QuoteListItemSerializer(quotes, many=True).data)


class QuoteDetailView(BasePortalView):
    """GET /quotes/{id} — Детали КП с позициями."""

    def get(self, request, pk):
        quote = _client_quotes(request.portal_company).filter(pk=pk).first()
        if not quote:
            raise Http404

        # Отмечаем первый просмотр
        if quote.first_viewed_at is None:
            quote.first_viewed_at = timezone.now()
            quote.save(update_fields=["first_viewed_at"])

        return Response(QuoteSerializer(quote).data)


class QuoteAcceptView(BasePortalView):
    """POST /quotes/{id}/accept — Акцепт КП по коду."""

    permission_classes = [IsPortalAuthenticated, CanAct]
    # Жёсткий потолок попыток кода поверх общего лимита сессии (FIX-15).
    throttle_classes = [PortalSessionRateThrottle, PortalAcceptRateThrottle]

    def post(self, request, pk):
        serializer = QuoteAcceptSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")

        code = serializer.validated_data["code"].strip()

        quote = (
            Quote.objects.filter(
                pk=pk,
                deal__company=request.portal_company,
            )
            .select_related("status")
            .first()
        )
        if not quote:
            raise Http404

        current_code = quote.status.code if quote.status else ""
        if current_code == QuoteStatusCode.APPROVED:
            raise PortalConflict("QUOTE_FINALIZED")
        if current_code == QuoteStatusCode.REJECTED:
            raise PortalConflict("QUOTE_FINALIZED")
        if quote.valid_until and quote.valid_until < timezone.localdate():
            raise PortalConflict("QUOTE_EXPIRED")

        # Код акцепта — одноразовый, с TTL и лимитом попыток; погашение и акцепт — одна транзакция
        # (crm.services.public_page, общий путь с публичной страницей КП). Мастер-кода нет (FIX-02).
        accepted, error = verify_code_and_accept(quote, code, request_ip=request.META.get("REMOTE_ADDR", ""))
        if error == "QUOTE_ALREADY_DECIDED":
            raise PortalConflict("QUOTE_FINALIZED")
        if error:
            raise PortalConflict("QUOTE_CODE_INVALID")

        quote.refresh_from_db()
        return QuoteDetailView().get(request, pk)


class QuoteRejectView(BasePortalView):
    """POST /quotes/{id}/reject — Отклонение КП с причиной."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        reason = _parse_reason(request.data)

        quote = (
            Quote.objects.filter(
                pk=pk,
                deal__company=request.portal_company,
            )
            .select_related("status")
            .first()
        )
        if not quote:
            raise Http404

        current_code = quote.status.code if quote.status else ""
        if current_code in (QuoteStatusCode.APPROVED, QuoteStatusCode.REJECTED):
            raise PortalConflict("QUOTE_FINALIZED")

        from crm.services.quotes.lifecycle_accept import perform_quote_rejection

        ip = request.META.get("REMOTE_ADDR")
        perform_quote_rejection(
            quote.id,
            rejected_by_user=None,
            reason=reason,
            contact_email=request.portal_contact.email,
            request_ip=ip,
        )

        quote.refresh_from_db()
        return QuoteDetailView().get(request, pk)


# ── 5. Contracts ────────────────────────────────────────────────────────────


class ContractListView(BasePortalView):
    """GET /contracts — Договоры клиента."""

    def get(self, request):
        contracts = (
            Contract.objects.filter(deal__company=request.portal_company)
            .select_related("status", "deal")
            .order_by("-created_at")
        )
        return Response(ContractSerializer(contracts, many=True).data)


class ContractSignView(BasePortalView):
    """POST /contracts/{id}/sign — Подписание договора клиентом."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        contract = (
            Contract.objects.filter(
                pk=pk,
                deal__company=request.portal_company,
            )
            .select_related("status", "deal")
            .first()
        )
        if not contract:
            raise Http404

        current_status = contract.status.code if contract.status else ""
        if current_status in ("SIGNED", "ACTIVE", "COMPLETED"):
            raise PortalConflict("CONTRACT_FINALIZED")

        # Подписываем договор от имени покупателя
        from crm.models import ContractStatus

        signed_status = ContractStatus.objects.filter(code="SIGNED").first()
        contract.status = signed_status
        now = timezone.now()
        fields = ["status", "updated_at"]
        if hasattr(contract, "client_signed_at"):
            contract.client_signed_at = now
            fields.append("client_signed_at")
        if hasattr(contract, "signed_at"):
            contract.signed_at = now
            fields.append("signed_at")
        contract.save(update_fields=fields)

        # Продвигаем сделку
        transition_deal_stage(
            contract.deal,
            DealStageCode.CONTRACT_SIGNED,
            actor=None,
            reason=f"Договор {contract.number} подписан клиентом в Cabinet",
        )

        contract.refresh_from_db()
        return Response(ContractSerializer(contract).data, status=status.HTTP_200_OK)


# ── 6. Invoices ─────────────────────────────────────────────────────────────


class InvoiceListView(BasePortalView):
    """GET /invoices — Счета клиента."""

    def get(self, request):
        invoices = (
            Invoice.objects.filter(deal__company=request.portal_company)
            .exclude(status__code=InvoiceStatusCode.DRAFT)
            .select_related("status", "deal", "currency")
            .order_by("-created_at")
        )
        return Response(InvoiceSerializer(invoices, many=True).data)


# ── 7. Acts ─────────────────────────────────────────────────────────────────


class ActListView(BasePortalView):
    """GET /acts — Акты выполненных работ."""

    def get(self, request):
        acts = (
            Act.objects.filter(deal__company=request.portal_company)
            .select_related("status", "deal")
            .order_by("-created_at")
        )
        return Response(ActSerializer(acts, many=True).data)


class ActAcceptView(BasePortalView):
    """POST /acts/{id}/accept — Приёмка акта заказчиком."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        act = (
            Act.objects.filter(
                pk=pk,
                deal__company=request.portal_company,
            )
            .select_related("status", "deal", "invoice")
            .first()
        )
        if not act:
            raise Http404

        if act.status and act.status.code == "SIGNED":
            raise PortalConflict("ACT_FINALIZED")

        from crm.models import ActStatus

        signed_status = ActStatus.objects.filter(code="SIGNED").first()
        act.status = signed_status
        act.signed_at = timezone.now()
        act.save(update_fields=["status", "signed_at", "updated_at"])

        # Продвигаем сделку к закрытию
        transition_deal_stage(
            act.deal,
            DealStageCode.CLOSED_WON,
            actor=None,
            reason=f"Акт {act.number} принят заказчиком в Cabinet",
        )

        act.refresh_from_db()
        return Response(ActSerializer(act).data)


class ActReturnView(BasePortalView):
    """POST /acts/{id}/return — Возврат акта с замечанием."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        reason = _parse_reason(request.data)

        act = (
            Act.objects.filter(
                pk=pk,
                deal__company=request.portal_company,
            )
            .select_related("status", "deal", "invoice")
            .first()
        )
        if not act:
            raise Http404

        if act.status and act.status.code == "SIGNED":
            raise PortalConflict("ACT_FINALIZED")

        from crm.models import ActStatus

        returned_status = ActStatus.objects.filter(code__in=["RETURNED", "REJECTED"]).first()
        act.status = returned_status
        if hasattr(act, "rejection_reason"):
            act.rejection_reason = reason
            act.save(update_fields=["status", "rejection_reason", "updated_at"])
        elif hasattr(act, "return_reason"):
            act.return_reason = reason
            act.save(update_fields=["status", "return_reason", "updated_at"])
        else:
            act.save(update_fields=["status", "updated_at"])

        ActivityLog.objects.create(
            deal=act.deal,
            action="Акт возвращён",
            event_code="act.returned",
            detail=f"Клиент вернул акт {act.number} с замечанием: {reason}",
            event_params={"act_id": act.id, "reason": reason},
        )

        act.refresh_from_db()
        return Response(ActSerializer(act).data)


# ── 8. Deliveries ───────────────────────────────────────────────────────────


class DeliveryListView(BasePortalView):
    """GET /deliveries — Строки поставки по сделкам клиента (проекция клиента: без поставщика и цен)."""

    def get(self, request):
        fulfillments = (
            Fulfillment.objects.filter(deal__company=request.portal_company)
            .select_related("status", "deal")
            .order_by("-created_at")
        )
        return Response(DeliveryLineSerializer(delivery_lines(fulfillments), many=True).data)


# ── 9. Documents & Files ────────────────────────────────────────────────────


class DocumentListView(BasePortalView):
    """GET /documents — Документы по сделкам клиента."""

    def get(self, request):
        docs = (
            GeneratedDocument.objects.filter(deal__company=request.portal_company)
            .select_related("template__kind", "deal")
            .order_by("-created_at")
        )
        return Response(PortalDocumentSerializer(docs, many=True).data)


class DocumentFileView(BasePortalView):
    """GET /documents/{id}/file — Скачивание PDF документа (202 если генерируется)."""

    def get(self, request, pk):
        doc = (
            GeneratedDocument.objects.filter(
                pk=pk,
                deal__company=request.portal_company,
            )
            .select_related("deal")
            .first()
        )
        if not doc:
            raise Http404

        if doc.pdf_file and hasattr(doc.pdf_file, "open"):
            try:
                response = FileResponse(
                    doc.pdf_file.open("rb"),
                    content_type="application/pdf",
                    as_attachment=True,
                    filename=f"{doc.number}.pdf",
                )
                return response
            except Exception as exc:
                logger.warning("Could not read pdf_file for document %s: %s", doc.id, exc)

        # Если файл еще рендерится (M2-ERP-03 / 202 retry-after)
        return Response(
            {"detail": "DOCUMENT_PENDING"},
            status=status.HTTP_202_ACCEPTED,
            headers={"Retry-After": "2"},
        )


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
        contacts = Contact.objects.filter(company=request.portal_company).order_by("-is_primary", "name")
        return Response(TeamMemberSerializer(contacts, many=True).data)


class TeamInviteView(BasePortalView):
    """POST /team/invite — Приглашение коллеги в кабинет."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request):
        serializer = TeamInviteSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")

        data = serializer.validated_data
        email = data.get("email", "").strip().lower()
        phone = data.get("phone", "").strip()

        # Проверка дубликата контакта
        existing = Contact.objects.filter(company=request.portal_company)
        if email and existing.filter(email__iexact=email).exists():
            raise PortalValidationError("TEAM_MEMBER_EXISTS")
        if phone and existing.filter(phone=phone).exists():
            raise PortalValidationError("TEAM_MEMBER_EXISTS")

        channels = data.get("channels") or ["email"]
        pref_channel = (
            "both" if ("email" in channels and "telegram" in channels) else (channels[0] if channels else "email")
        )

        contact = Contact.objects.create(
            company=request.portal_company,
            name=data["name"].strip(),
            email=email,
            phone=phone,
            language=data.get("language", "ru"),
            can_act=data.get("can_act", False),
            preferred_channel=pref_channel,
            is_primary=False,
            invited_at=timezone.now(),
        )

        # Отправляем приглашение по выбранным каналам
        invite_contact_to_portal(
            contact=contact,
            actor=getattr(request, "portal_contact", None),
            channel=pref_channel,
            language=contact.language,
        )

        return Response(TeamMemberSerializer(contact).data, status=status.HTTP_201_CREATED)
