"""`/api/v1/finance/bank-changes/` — запросы контрагентов на смену банковских реквизитов (FX-4, решение владельца 2026-11-08)."""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from portal.desk import service_bank_changes as desk
from portal.desk.serializers import DeskBankChange, DeskBankChangeListResponse, DeskBankChangeRejectIn
from portal.exceptions import PortalConflict
from portal.models import BankDetailsChangeRequest, BankDetailsChangeStatus
from portal.services import bank_details_change as service
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, REFUSED, DeskViewSet

CONFLICT = OpenApiResponse(
    description="Запрос решён иначе (`BANK_CHANGE_NOT_PENDING`), реквизиты изменились (`BANK_CHANGE_STALE`) или компания в архиве (`COMPANY_ARCHIVED`)."
)
DECIDE = "finance.payment"


class BankChangeDeskViewSet(DeskViewSet):
    required_permissions = {"approve": DECIDE, "reject": DECIDE}
    lookup_value_regex = r"\d+"
    queryset = BankDetailsChangeRequest.objects.none()
    serializer_class = DeskBankChange

    @extend_schema(
        operation_id="finance_bank_changes_list",
        summary="List bank details change requests",
        description="Очередь запросов контрагентов на смену реквизитов; `finance.view` или `finance.payment`. Полные реквизиты — только с `finance.payment`, остальным маска.",
        parameters=[OpenApiParameter("status", str, required=False, enum=BankDetailsChangeStatus.values)],
        responses={200: DeskBankChangeListResponse, 403: FORBIDDEN},
        tags=["Finance"],
    )
    def list(self, request):
        if not desk.can_read(request.user):
            return Response({"detail": "ROLE_NOT_PERMITTED"}, status=status.HTTP_403_FORBIDDEN)
        value = request.query_params.get("status") or None
        if value is not None and value not in BankDetailsChangeStatus.values:
            value = None
        return Response(desk.queue(status_filter=value, full=desk.can_decide(request.user)))

    def _decided(self, request, item) -> Response:
        return Response(desk.row(item, full=desk.can_decide(request.user)))

    @extend_schema(
        operation_id="finance_bank_changes_approve",
        summary="Approve a bank details change",
        description="Применяет новые реквизиты компании. Повтор на подтверждённом запросе — тот же ответ без второго эффекта.",
        request=None,
        responses={200: DeskBankChange, 403: FORBIDDEN, 404: NOT_FOUND, 409: CONFLICT},
        tags=["Finance"],
    )
    @action(detail=True, methods=["post"], url_path="approve", url_name="approve")
    def approve(self, request, pk=None):
        try:
            item = service.approve(int(pk), actor=request.user)
        except BankDetailsChangeRequest.DoesNotExist:
            return Response({"detail": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        except PortalConflict as error:
            return Response({"detail": error.detail}, status=status.HTTP_409_CONFLICT)
        return self._decided(request, item)

    @extend_schema(
        operation_id="finance_bank_changes_reject",
        summary="Reject a bank details change",
        description="Отклоняет запрос с обязательной причиной; реквизиты не меняются. Повтор на отклонённом — тот же ответ.",
        request=DeskBankChangeRejectIn,
        responses={200: DeskBankChange, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND, 409: CONFLICT},
        tags=["Finance"],
    )
    @action(detail=True, methods=["post"], url_path="reject", url_name="reject")
    def reject(self, request, pk=None):
        body = DeskBankChangeRejectIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            item = service.reject(int(pk), actor=request.user, reason=body.validated_data["reason"].strip())
        except BankDetailsChangeRequest.DoesNotExist:
            return Response({"detail": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        except PortalConflict as error:
            return Response({"detail": error.detail}, status=status.HTTP_409_CONFLICT)
        return self._decided(request, item)
