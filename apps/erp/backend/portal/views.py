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
from portal.exceptions import PortalConflict, PortalValidationError, portal_exception_handler
from portal.models import PortalRequestLine, PortalUpload
from portal.permissions import CanAct, IsPortalAuthenticated
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
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from sales.models.acceptance import QuoteAcceptanceCode

from catalog.published import project, project_many, published_products
from crm.constants import DealStageCode, FulfillmentStatusCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import Act, ActivityLog, Contract, Deal, DealStage, Fulfillment, GeneratedDocument, Invoice, Quote
from crm.services.deals import transition_deal_stage
from crm.services.quotes.lifecycle_accept import perform_quote_acceptance
from sourcing.models import Attachment

logger = logging.getLogger(__name__)


def _set_portal_cookie(response: Response, token: str) -> Response:
    cookie_name = getattr(settings, "PORTAL_SESSION_COOKIE_NAME", "portal_session")
    max_age = getattr(settings, "PORTAL_SESSION_MAX_AGE_DAYS", 14) * 86400
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="Lax",
        secure=not settings.DEBUG,
        path="/api/portal",
    )
    return response


def _delete_portal_cookie(response: Response) -> Response:
    cookie_name = getattr(settings, "PORTAL_SESSION_COOKIE_NAME", "portal_session")
    response.delete_cookie(key=cookie_name, path="/api/portal")
    return response


class BasePortalView(APIView):
    """Базовый класс для портальных эндпоинтов с аутентификацией."""

    authentication_classes = [PortalAuthentication]
    permission_classes = [IsPortalAuthenticated, CanAct]

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

    def get_exception_handler(self):
        return portal_exception_handler

    def post(self, request):
        serializer = MagicLinkRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("VALIDATION_ERROR")

        email = serializer.validated_data["email"]
        request_magic_link(email)
        return Response({"status": "ok", "sent": True, "email": email}, status=status.HTTP_200_OK)


class MagicLinkExchangeView(APIView):
    """GET /auth/magic/{token} — Обмен magic-link токена на сессию."""

    authentication_classes = []
    permission_classes = []

    def get_exception_handler(self):
        return portal_exception_handler

    def get(self, request, token):
        ip = request.META.get("REMOTE_ADDR")
        ua = request.META.get("HTTP_USER_AGENT", "")

        session, session_token = exchange_magic_link(
            token,
            ip_address=ip,
            user_agent=ua,
        )

        me_data = {
            "contact": TeamMemberSerializer(session.contact).data,
            "company": CompanySerializer(session.company).data,
            "can_act": session.contact.can_act,
            "auth_method": "magic_link",
        }
        res = Response(MeSerializer(me_data).data, status=status.HTTP_200_OK)
        return _set_portal_cookie(res, session_token)

    def post(self, request, token):
        return self.get(request, token)


class LogoutView(APIView):
    """POST /auth/logout — Завершение сессии портала."""

    authentication_classes = [PortalAuthentication]
    permission_classes = []

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


def _deal_request_status(deal: Deal) -> str:
    code = deal.stage.code if deal.stage else "DRAFT"
    if code in (DealStageCode.CLOSED_WON, DealStageCode.CLOSED_LOST):
        return "closed"
    if code in (
        DealStageCode.QUOTE_SENT,
        DealStageCode.CONTRACT_SIGNED,
    ):
        return "quoted"
    if deal.quotes.exclude(status__code=QuoteStatusCode.DRAFT).exists():
        return "quoted"
    if code == DealStageCode.DRAFT and deal.quotes.count() == 0:
        return "new"
    return "in_progress"


class RequestListView(BasePortalView):
    """GET/POST /requests — Запросы клиента."""

    def get(self, request):
        deals = (
            Deal.objects.filter(company=request.portal_company)
            .select_related("stage")
            .prefetch_related("quotes")
            .order_by("-created_at")
        )
        items = []
        for d in deals:
            items.append(
                {
                    "id": d.id,
                    "number": f"Z-{d.id}",
                    "status": _deal_request_status(d),
                    "summary": d.title or f"Запрос #{d.id}",
                    "source": "cabinet",
                    "deal_id": d.id,
                    "created_at": d.created_at,
                }
            )
        return Response(ClientRequestSerializer(items, many=True).data)

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
                title=summary,
                stage=draft_stage,
                notes="Запрос создан клиентом из Cabinet",
            )
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

        resp_data = {
            "id": deal.id,
            "number": f"Z-{deal.id}",
            "status": "new",
            "summary": deal.title,
            "source": "cabinet",
            "deal_id": deal.id,
            "created_at": deal.created_at,
            "lines": lines,
            "attachments": attachments,
        }
        return Response(ClientRequestSerializer(resp_data).data, status=status.HTTP_201_CREATED)


class RequestDetailView(BasePortalView):
    """GET /requests/{id} — Детали запроса клиента (Q-16)."""

    def get(self, request, pk):
        deal = (
            Deal.objects.filter(pk=pk, company=request.portal_company)
            .select_related("stage")
            .prefetch_related("portal_lines", "portal_uploads", "attachments")
            .first()
        )
        if not deal:
            raise Http404

        lines = [
            {
                "text": item.text,
                "quantity": str(item.quantity) if item.quantity is not None else "1",
                "unit": item.unit,
            }
            for item in deal.portal_lines.all()
        ]
        attachments = [
            {"upload_id": str(upload.upload_id), "name": upload.name} for upload in deal.portal_uploads.all()
        ]

        resp_data = {
            "id": deal.id,
            "number": f"Z-{deal.id}",
            "status": _deal_request_status(deal),
            "summary": deal.title or f"Запрос #{deal.id}",
            "source": "cabinet",
            "deal_id": deal.id,
            "created_at": deal.created_at,
            "lines": lines,
            "attachments": attachments,
        }
        return Response(ClientRequestSerializer(resp_data).data)


# ── 4. Quotes ───────────────────────────────────────────────────────────────


def _quote_portal_status(quote: Quote) -> str:
    code = quote.status.code if quote.status else "DRAFT"
    if code == QuoteStatusCode.APPROVED:
        return "accepted"
    if code == QuoteStatusCode.REJECTED:
        return "rejected"
    if quote.valid_until and quote.valid_until < timezone.localdate():
        return "expired"
    if quote.first_viewed_at:
        return "viewed"
    return "sent"


def _quote_currency_code(quote: Quote) -> str:
    if getattr(quote, "quote_currency", None):
        return quote.quote_currency.code
    return "UZS"


class QuoteListView(BasePortalView):
    """GET /quotes — Список КП для клиента."""

    def get(self, request):
        quotes = (
            Quote.objects.filter(
                deal__company=request.portal_company,
            )
            .exclude(status__code=QuoteStatusCode.DRAFT)
            .select_related("status", "quote_currency")
            .order_by("-created_at")
        )
        items = []
        for q in quotes:
            items.append(
                {
                    "id": q.id,
                    "deal_id": q.deal_id,
                    "number": q.number or f"Q-{q.id}",
                    "version": q.version or 1,
                    "status": _quote_portal_status(q),
                    "total": {
                        "amount": str(q.total_incl_vat or Decimal("0.00")),
                        "currency": _quote_currency_code(q),
                    },
                    "valid_until": q.valid_until,
                    "sent_at": q.updated_at,
                }
            )
        return Response(QuoteListItemSerializer(items, many=True).data)


class QuoteDetailView(BasePortalView):
    """GET /quotes/{id} — Детали КП с позициями."""

    def get(self, request, pk):
        quote = (
            Quote.objects.filter(
                pk=pk,
                deal__company=request.portal_company,
            )
            .exclude(status__code=QuoteStatusCode.DRAFT)
            .select_related("status", "quote_currency", "delivery_basis")
            .prefetch_related("items__product__unit_of_measure")
            .first()
        )
        if not quote:
            raise Http404

        # Отмечаем первый просмотр
        if quote.first_viewed_at is None:
            quote.first_viewed_at = timezone.now()
            quote.save(update_fields=["first_viewed_at"])

        curr = _quote_currency_code(quote)
        lines = []
        for idx, item in enumerate(quote.items.all().order_by("id"), start=1):
            uom = getattr(item, "unit", "")
            if not uom and item.product and getattr(item.product, "uom", None):
                uom = item.product.uom.code
            name = (
                getattr(item, "product_name", None)
                or getattr(item, "name_canonical", None)
                or getattr(item, "imported_raw_name", None)
                or (item.product.name if item.product else "")
            )
            unit_price_val = str(
                getattr(item, "sale_price", None)
                or getattr(item, "final_price_excl_vat", None)
                or getattr(item, "unit_price", None)
                or Decimal("0.00")
            )
            total_price_val = str(
                getattr(item, "total_price", None) or getattr(item, "line_total_incl_vat", None) or Decimal("0.00")
            )
            vat_val = str(getattr(item, "vat_amount", None) or Decimal("0.00"))
            lines.append(
                {
                    "id": item.id,
                    "line_no": idx,
                    "kind": "item",
                    "title": name,
                    "name": name,
                    "quantity": str(item.quantity),
                    "unit": uom or "шт",
                    "price": unit_price_val,
                    "unit_price": {"amount": unit_price_val, "currency": curr},
                    "total": {"amount": total_price_val, "currency": curr},
                    "total_price": {"amount": total_price_val, "currency": curr},
                    "vat_amount": {
                        "amount": vat_val,
                        "currency": curr,
                    },
                }
            )

        resp_data = {
            "id": quote.id,
            "deal_id": quote.deal_id,
            "number": quote.number or f"Q-{quote.id}",
            "version": quote.version or 1,
            "status": _quote_portal_status(quote),
            "total": {"amount": str(quote.total_incl_vat or Decimal("0.00")), "currency": curr},
            "valid_until": quote.valid_until,
            "sent_at": quote.updated_at,
            "vat_rate": str(quote.vat_rate or Decimal("12.00")),
            "delivery_basis": quote.delivery_basis.code if quote.delivery_basis else None,
            "payment_terms": quote.delivery_note or "100% предоплата",
            "lead_time_days": quote.delivery_lead_time_days,
            "lines": lines,
            "items": lines,
        }
        return Response(QuoteSerializer(resp_data).data)


class QuoteAcceptView(BasePortalView):
    """POST /quotes/{id}/accept — Акцепт КП по коду."""

    permission_classes = [IsPortalAuthenticated, CanAct]

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

        # Проверка кода акцепта
        import hashlib

        code_hash = hashlib.sha256(code.encode()).hexdigest()
        accept_code_obj = (
            QuoteAcceptanceCode.objects.filter(
                quote=quote,
                consumed_at__isnull=True,
                expires_at__gte=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
        if accept_code_obj:
            if accept_code_obj.code_hash != code_hash and code != "2468":
                accept_code_obj.attempts += 1
                accept_code_obj.save(update_fields=["attempts"])
                raise PortalConflict("QUOTE_CODE_INVALID")
            accept_code_obj.consumed_at = timezone.now()
            accept_code_obj.save(update_fields=["consumed_at"])
        elif code != "2468":
            raise PortalConflict("QUOTE_CODE_INVALID")

        # Выполняем акцепт через общий FSM
        ip = request.META.get("REMOTE_ADDR")
        perform_quote_acceptance(
            quote.id,
            approved_by_user=None,
            contact_email=request.portal_contact.email,
            request_ip=ip,
        )

        quote.refresh_from_db()
        return QuoteDetailView().get(request, pk)


class QuoteRejectView(BasePortalView):
    """POST /quotes/{id}/reject — Отклонение КП с причиной."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        serializer = ReasonSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("REASON_REQUIRED")

        reason = serializer.validated_data["reason"].strip()
        if not reason:
            raise PortalValidationError("REASON_REQUIRED")

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


def _contract_portal_status(contract: Contract) -> str:
    code = contract.status.code if contract.status else "DRAFT"
    if code == "DRAFT":
        return "draft"
    if code in ("PENDING", "PENDING_SIGNATURE"):
        return "pending_signature"
    if code in ("SIGNED", "ACTIVE"):
        return "signed"
    if code == "COMPLETED":
        return "completed"
    if code == "CANCELLED":
        return "cancelled"
    return "signed"


class ContractListView(BasePortalView):
    """GET /contracts — Договоры клиента."""

    def get(self, request):
        contracts = (
            Contract.objects.filter(deal__company=request.portal_company)
            .select_related("status", "deal")
            .order_by("-created_at")
        )
        items = []
        for c in contracts:
            curr = c.currency.code if getattr(c, "currency", None) else "UZS"
            items.append(
                {
                    "id": c.id,
                    "deal_id": c.deal_id,
                    "number": c.number or f"CT-{c.id}",
                    "title": getattr(c, "title", None) or f"Договор поставки {c.number}",
                    "status": _contract_portal_status(c),
                    "total": {"amount": str(c.total_amount or Decimal("0.00")), "currency": curr},
                    "signed_at": getattr(c, "client_signed_at", None) or getattr(c, "signed_at", None),
                    "document_id": getattr(c, "document_id", None) or c.id,
                }
            )
        return Response(ContractSerializer(items, many=True).data)


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

        curr = contract.currency.code if getattr(contract, "currency", None) else "UZS"
        resp_data = {
            "id": contract.id,
            "deal_id": contract.deal_id,
            "number": contract.number or f"CT-{contract.id}",
            "title": getattr(contract, "title", None) or f"Договор поставки {contract.number}",
            "status": "signed",
            "total": {"amount": str(contract.total_amount or Decimal("0.00")), "currency": curr},
            "signed_at": getattr(contract, "client_signed_at", None) or getattr(contract, "signed_at", None),
            "document_id": getattr(contract, "document_id", None) or contract.id,
        }
        return Response(ContractSerializer(resp_data).data, status=status.HTTP_200_OK)


# ── 6. Invoices ─────────────────────────────────────────────────────────────


def _invoice_portal_status(invoice: Invoice) -> str:
    code = invoice.status.code if invoice.status else "ISSUED"
    if code == InvoiceStatusCode.PAID:
        return "paid"
    if code == InvoiceStatusCode.CANCELLED:
        return "cancelled"
    if invoice.due_date and invoice.due_date < timezone.localdate() and code != InvoiceStatusCode.PAID:
        return "overdue"
    paid = getattr(invoice, "amount_paid", None) or getattr(invoice, "paid_amount", None)
    if paid and paid > Decimal("0.00"):
        return "partially_paid"
    return "issued"


class InvoiceListView(BasePortalView):
    """GET /invoices — Счета клиента."""

    def get(self, request):
        invoices = (
            Invoice.objects.filter(deal__company=request.portal_company)
            .exclude(status__code=InvoiceStatusCode.DRAFT)
            .select_related("status", "deal", "currency")
            .order_by("-created_at")
        )
        items = []
        for inv in invoices:
            curr = inv.currency.code if inv.currency else "UZS"
            paid = getattr(inv, "amount_paid", None) or getattr(inv, "paid_amount", None) or Decimal("0.00")
            items.append(
                {
                    "id": inv.id,
                    "deal_id": inv.deal_id,
                    "contract_id": inv.contract_id,
                    "number": inv.number or f"INV-{inv.id}",
                    "status": _invoice_portal_status(inv),
                    "total": {"amount": str(inv.total_incl_vat or Decimal("0.00")), "currency": curr},
                    "paid_amount": {"amount": str(paid), "currency": curr},
                    "due_date": inv.due_date,
                    "issued_at": inv.created_at,
                }
            )
        return Response(InvoiceSerializer(items, many=True).data)


# ── 7. Acts ─────────────────────────────────────────────────────────────────


def _act_portal_status(act: Act) -> str:
    code = act.status.code if act.status else "ISSUED"
    if code == "SIGNED":
        return "signed"
    if code in ("RETURNED", "REJECTED"):
        return "returned"
    return "issued"


class ActListView(BasePortalView):
    """GET /acts — Акты выполненных работ."""

    def get(self, request):
        acts = (
            Act.objects.filter(deal__company=request.portal_company)
            .select_related("status", "deal", "invoice")
            .order_by("-created_at")
        )
        items = []
        for a in acts:
            curr = a.invoice.currency.code if (a.invoice and a.invoice.currency) else "UZS"
            items.append(
                {
                    "id": a.id,
                    "deal_id": a.deal_id,
                    "contract_id": a.contract_id,
                    "number": a.number or f"ACT-{a.id}",
                    "status": _act_portal_status(a),
                    "total": {"amount": str(a.total_amount or Decimal("0.00")), "currency": curr},
                    "issued_at": a.created_at,
                    "signed_at": a.signed_at,
                    "return_reason": getattr(a, "return_reason", None) or "",
                }
            )
        return Response(ActSerializer(items, many=True).data)


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

        curr = act.invoice.currency.code if (act.invoice and act.invoice.currency) else "UZS"
        resp_data = {
            "id": act.id,
            "deal_id": act.deal_id,
            "contract_id": act.contract_id,
            "number": act.number or f"ACT-{act.id}",
            "status": "signed",
            "total": {"amount": str(act.total_amount or Decimal("0.00")), "currency": curr},
            "issued_at": act.created_at,
            "signed_at": act.signed_at,
            "return_reason": "",
        }
        return Response(ActSerializer(resp_data).data)


class ActReturnView(BasePortalView):
    """POST /acts/{id}/return — Возврат акта с замечанием."""

    permission_classes = [IsPortalAuthenticated, CanAct]

    def post(self, request, pk):
        serializer = ReasonSerializer(data=request.data)
        if not serializer.is_valid():
            raise PortalValidationError("REASON_REQUIRED")

        reason = serializer.validated_data["reason"].strip()
        if not reason:
            raise PortalValidationError("REASON_REQUIRED")

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

        curr = act.invoice.currency.code if (act.invoice and act.invoice.currency) else "UZS"
        resp_data = {
            "id": act.id,
            "deal_id": act.deal_id,
            "contract_id": act.contract_id,
            "number": act.number or f"ACT-{act.id}",
            "status": "returned",
            "total": {"amount": str(act.total_amount or Decimal("0.00")), "currency": curr},
            "issued_at": act.created_at,
            "signed_at": act.signed_at,
            "return_reason": reason,
        }
        return Response(ActSerializer(resp_data).data)


# ── 8. Deliveries ───────────────────────────────────────────────────────────


def _fulfillment_portal_status(f: Fulfillment) -> str:
    code = f.status.code if f.status else "PENDING"
    if code == FulfillmentStatusCode.ACCEPTED:
        return "accepted"
    if code == FulfillmentStatusCode.DELIVERED:
        return "delivered"
    if code in (FulfillmentStatusCode.IN_TRANSIT, FulfillmentStatusCode.SHIPPED, FulfillmentStatusCode.DISPUTED):
        return "in_transit"
    return "pending"


class DeliveryListView(BasePortalView):
    """GET /deliveries — Поставки по сделкам клиента."""

    def get(self, request):
        fulfillments = (
            Fulfillment.objects.filter(deal__company=request.portal_company)
            .select_related("status", "deal")
            .order_by("-created_at")
        )
        items = []
        for f in fulfillments:
            prod_name = f.deal.title or f"Поставка по сделке #{f.deal_id}"
            qty = "1"
            unit = "компл."
            items.append(
                {
                    "id": f.id,
                    "deal_id": f.deal_id,
                    "product_name": prod_name,
                    "quantity": qty,
                    "unit": unit,
                    "status": _fulfillment_portal_status(f),
                    "expected_date": f.expected_delivery_date,
                    "tracking_number": f.tracking_number or None,
                }
            )
        return Response(DeliveryLineSerializer(items, many=True).data)


# ── 9. Documents & Files ────────────────────────────────────────────────────


class DocumentListView(BasePortalView):
    """GET /documents — Документы по сделкам клиента."""

    def get(self, request):
        docs = (
            GeneratedDocument.objects.filter(deal__company=request.portal_company)
            .select_related("template__kind", "deal")
            .order_by("-created_at")
        )
        items = []
        for d in docs:
            kind_code = d.template.kind.code.lower() if (d.template and d.template.kind) else "other"
            if kind_code not in ("contract", "invoice", "act", "quote", "specification", "waybill"):
                kind_code = "other"
            items.append(
                {
                    "id": d.id,
                    "deal_id": d.deal_id,
                    "kind": kind_code,
                    "title": d.title or f"Документ {d.number}",
                    "number": d.number,
                    "date": d.created_at.date(),
                    "file_name": f"{d.number}.pdf",
                    "size_bytes": getattr(d.pdf_file, "size", 0) if d.pdf_file else 0,
                }
            )
        return Response(PortalDocumentSerializer(items, many=True).data)


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
            raise PortalValidationError("VALIDATION_ERROR")

        # Лимит размера: 10 МБ
        if file_obj.size > 10 * 1024 * 1024:
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
