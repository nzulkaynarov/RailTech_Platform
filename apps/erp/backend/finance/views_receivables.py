"""Счета и оплаты бухгалтера (D2-4): доска по вкладкам, карточка, подтверждение оплаты, платёжка клиента, запрос платёжки.

Чтение — сотрудник с `finance.view`, `finance.invoice` или `finance.payment` (бухгалтер, директор, менеджер); остальные роли
бэк-офиса (снабжение, инженер) не видят счетов клиентов — 403 `ROLE_NOT_PERMITTED`, даже если зайти в ERP напрямую, мимо Платформы.
Действия — `finance.payment`. Объектная проверка — в сервисе: счёт обязан существовать, быть открытым (`ISSUED`,
`PARTIAL`, `OVERDUE`), платёжка — относиться к этому счёту. Тела отказов — `{"detail": "КОД"}` (CONVENTIONS ERP §5).
"""

import mimetypes

from django.core.exceptions import ValidationError
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from finance.models import PaymentConfirmation
from finance.serializers_receivables import (
    AttachConfirmationSerializer,
    ConfirmPaymentSerializer,
    ReceivableBoardSerializer,
    ReceivableCardSerializer,
    card,
    row,
)
from finance.services import receivables
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.file_streaming import stream_file_field
from core.permissions import RoleGatedViewMixin

READ_PERMISSIONS = ("finance.view", "finance.invoice", "finance.payment")
_NOT_FOUND = {"NOT_FOUND", "CONFIRMATION_NOT_FOUND"}
_FORBIDDEN = {"ROLE_NOT_PERMITTED", "MEMBER_REQUIRED_FOR_ACTION"}
_CONFLICT = {
    "PAYMENT_EXCEEDS_BALANCE_DUE",
    "INVOICE_NOT_ISSUED",
    "INVOICE_NOT_OPEN",
    "INVOICE_CANCELLED",
    "INVOICE_ALREADY_PAID",
    "PAYMENT_REFERENCE_CONFLICT",
}
_ERRORS = (
    "NOT_FOUND / CONFIRMATION_NOT_FOUND (404); ROLE_NOT_PERMITTED / MEMBER_REQUIRED_FOR_ACTION (403); "
    "PAYMENT_EXCEEDS_BALANCE_DUE / INVOICE_NOT_ISSUED / INVOICE_NOT_OPEN / INVOICE_CANCELLED / INVOICE_ALREADY_PAID / "
    "PAYMENT_REFERENCE_CONFLICT (409); PAYMENT_DATE_IN_FUTURE / PAYMENT_AMOUNT_MUST_BE_POSITIVE (400)"
)


class CanReadReceivables(BasePermission):
    """Счета клиентов видит сотрудник с правом на счета или оплаты (администратор — всегда)."""

    message = "ROLE_NOT_PERMITTED"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        from accounts.services.permissions import staff_has_permission

        return staff_has_permission(user, READ_PERMISSIONS)


def _error(code: str) -> Response:
    if code in _NOT_FOUND:
        http = status.HTTP_404_NOT_FOUND
    elif code in _FORBIDDEN:
        http = status.HTTP_403_FORBIDDEN
    elif code in _CONFLICT:
        http = status.HTTP_409_CONFLICT
    else:
        http = status.HTTP_400_BAD_REQUEST
    return Response({"detail": code}, status=http)


def _can_pay(user) -> bool:
    from accounts.services.permissions import staff_has_permission

    return bool(user.is_superuser or staff_has_permission(user, "finance.payment"))


def _card_response(request, invoice_id: int, *, http: int = status.HTTP_200_OK, replayed: bool = False) -> Response:
    invoice = receivables.get_invoice(invoice_id)
    if invoice is None:
        return _error("NOT_FOUND")
    data = card(invoice, may_pay=_can_pay(request.user), replayed=replayed)
    return Response(ReceivableCardSerializer(data).data, status=http)


class ReceivableBoardView(APIView):
    """GET — счета вкладки «Счетов и оплат» и число счетов на каждой вкладке."""

    permission_classes = [IsAuthenticated, CanReadReceivables]

    @extend_schema(
        summary="Счета и оплаты: таблица вкладки",
        operation_id="finance_receivables_board",
        parameters=[
            OpenApiParameter("tab", str, enum=list(receivables.TABS), description="Вкладка; по умолчанию `awaiting`."),
            OpenApiParameter("q", str, description="Поиск по номеру счёта и названию клиента."),
            OpenApiParameter("limit", int, description="Строк на странице, 1–100 (по умолчанию 50)."),
            OpenApiParameter("offset", int, description="Сколько строк пропустить."),
        ],
        responses={
            200: ReceivableBoardSerializer,
            400: OpenApiResponse(description="TAB_INVALID / PAGINATION_INVALID"),
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED"),
        },
        tags=["Finance"],
    )
    def get(self, request):
        tab = request.query_params.get("tab") or "awaiting"
        if tab not in receivables.TABS:
            return _error("TAB_INVALID")
        try:
            limit = int(request.query_params.get("limit", 50))
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            return _error("PAGINATION_INVALID")
        day = receivables.today()
        page, total = receivables.board(
            tab=tab, day=day, q=request.query_params.get("q", ""), limit=limit, offset=offset
        )
        data = {
            "tab": tab,
            "count": total,
            "counts": receivables.counts(day),
            "results": [row(invoice, day) for invoice in page],
        }
        return Response(ReceivableBoardSerializer(data).data)


class ReceivableCardView(APIView):
    """GET — карточка счёта: платёжки, платежи, остаток, журнал."""

    permission_classes = [IsAuthenticated, CanReadReceivables]

    @extend_schema(
        summary="Счета и оплаты: карточка счёта",
        operation_id="finance_receivables_card",
        responses={
            200: ReceivableCardSerializer,
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED"),
            404: OpenApiResponse(description="NOT_FOUND"),
        },
        tags=["Finance"],
    )
    def get(self, request, invoice_id: int):
        return _card_response(request, invoice_id)


class ReceivableConfirmPaymentView(RoleGatedViewMixin, APIView):
    """POST — «Подтвердить оплату» (полная или частичная) по выписке банка."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "finance.payment"}

    @extend_schema(
        summary="Подтвердить оплату счёта (сумма и дата по выписке)",
        operation_id="finance_receivables_confirm_payment",
        request=ConfirmPaymentSerializer,
        responses={
            200: ReceivableCardSerializer,
            400: OpenApiResponse(description=_ERRORS),
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED / MEMBER_REQUIRED_FOR_ACTION"),
            404: OpenApiResponse(description="NOT_FOUND / CONFIRMATION_NOT_FOUND"),
            409: OpenApiResponse(description="PAYMENT_EXCEEDS_BALANCE_DUE / INVOICE_ALREADY_PAID / ..."),
        },
        tags=["Finance"],
    )
    def post(self, request, invoice_id: int):
        body = ConfirmPaymentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        result, err = receivables.confirm_payment(
            invoice_id,
            request.user,
            amount=data["amount"],
            paid_at=data["paid_at"],
            reference=data["reference"],
            confirmation_id=data["confirmation_id"],
        )
        if err:
            return _error(err)
        assert result is not None
        return _card_response(request, invoice_id, replayed=result.replayed)


class ReceivableConfirmationsView(RoleGatedViewMixin, APIView):
    """POST — приложить платёжку клиента (файл) к открытому счёту."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "finance.payment"}
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary="Приложить платёжку клиента к счёту",
        operation_id="finance_receivables_attach_confirmation",
        request={"multipart/form-data": AttachConfirmationSerializer},
        responses={
            201: ReceivableCardSerializer,
            400: OpenApiResponse(description="Файл не принят или поле неверно"),
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED / MEMBER_REQUIRED_FOR_ACTION"),
            404: OpenApiResponse(description="NOT_FOUND"),
            409: OpenApiResponse(description="INVOICE_NOT_OPEN"),
        },
        tags=["Finance"],
    )
    def post(self, request, invoice_id: int):
        body = AttachConfirmationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        from core.validators import validate_document_upload

        try:
            validate_document_upload(data["file"])
        except ValidationError as exc:
            return Response({"detail": "; ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        confirmation, err = receivables.attach_confirmation(
            invoice_id,
            request.user,
            file=data["file"],
            source=data.get("source") or PaymentConfirmation.Source.MANUAL.value,
            claimed_amount=data.get("claimed_amount"),
            claimed_date=data.get("claimed_date"),
            note=data.get("note", ""),
        )
        if err:
            return _error(err)
        return _card_response(request, invoice_id, http=status.HTTP_201_CREATED)


class ReceivableConfirmationFileView(APIView):
    """GET — файл платёжки клиента потоком (приватное хранилище, только после проверки права и привязки к счёту)."""

    permission_classes = [IsAuthenticated, CanReadReceivables]

    @extend_schema(
        summary="Файл платёжки клиента",
        operation_id="finance_receivables_confirmation_file",
        responses={
            (200, "application/octet-stream"): OpenApiResponse(description="Содержимое файла"),
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED"),
            404: OpenApiResponse(description="Платёжки нет или она относится к другому счёту"),
        },
        tags=["Finance"],
    )
    def get(self, request, invoice_id: int, confirmation_id: int):
        confirmation = PaymentConfirmation.objects.filter(pk=confirmation_id, invoice_id=invoice_id).first()
        if confirmation is None or not confirmation.file:
            raise Http404("NOT_FOUND")
        content_type = mimetypes.guess_type(confirmation.original_name or confirmation.file.name)[0]
        return stream_file_field(confirmation.file, content_type=content_type or "application/octet-stream")


class ReceivableRequestPaymentDocView(RoleGatedViewMixin, APIView):
    """POST — отметить «платёжку запросили у клиента» (запись в журнале счёта)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "finance.payment"}

    @extend_schema(
        summary="Отметить запрос платёжки у клиента",
        operation_id="finance_receivables_request_payment_doc",
        request=None,
        responses={
            200: ReceivableCardSerializer,
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED / MEMBER_REQUIRED_FOR_ACTION"),
            404: OpenApiResponse(description="NOT_FOUND"),
            409: OpenApiResponse(description="INVOICE_NOT_OPEN"),
        },
        tags=["Finance"],
    )
    def post(self, request, invoice_id: int):
        _entry, err = receivables.request_payment_doc(invoice_id, request.user)
        if err:
            return _error(err)
        return _card_response(request, invoice_id)


__all__ = [
    "ReceivableBoardView",
    "ReceivableCardView",
    "ReceivableConfirmPaymentView",
    "ReceivableConfirmationFileView",
    "ReceivableConfirmationsView",
    "ReceivableRequestPaymentDocView",
]
