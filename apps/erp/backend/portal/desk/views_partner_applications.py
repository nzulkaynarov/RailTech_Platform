"""`/api/v1/catalog/partner-applications/` — очередь заявок кандидатов в партнёры (PART-ONBOARD-2).

Чтение — любой сотрудник бэк-офиса, действия договорного шлюза (отправка договора, одобрение,
отклонение) — `supply.manage`.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from parties.models import PartnerApplication
from portal.desk import service_partner_applications as service
from portal.desk.serializers import (
    DeskPartnerApplicationApproveIn,
    DeskPartnerApplicationDetail,
    DeskPartnerApplicationListResponse,
    DeskPartnerApplicationRejectIn,
    DeskPartnerApplicationSendContractIn,
)
from portal.desk.service import AccessError
from rest_framework.decorators import action
from rest_framework.response import Response

from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, REFUSED, DeskViewSet

SUPPLY_MANAGE = "supply.manage"


def _refused(error: AccessError) -> Response:
    return Response({"detail": error.code}, status=error.status)


class PartnerApplicationDeskViewSet(DeskViewSet):
    required_permissions = {
        "send_contract": SUPPLY_MANAGE,
        "approve": SUPPLY_MANAGE,
        "reject": SUPPLY_MANAGE,
    }
    lookup_value_regex = r"\d+"
    queryset = PartnerApplication.objects.none()
    serializer_class = DeskPartnerApplicationDetail

    @extend_schema(
        operation_id="catalog_partner_applications_list",
        summary="List partner applications",
        description="Очередь заявок кандидатов в партнёры со счётчиком ожидающих (`pending_count`).",
        parameters=[
            OpenApiParameter(
                "status", str, required=False, description="Фильтр по статусу (submitted, contract_sent...)"
            ),
        ],
        responses={200: DeskPartnerApplicationListResponse},
        tags=["Catalog"],
    )
    def list(self, request):
        status_filter = request.query_params.get("status")
        return Response(service.list_applications(status_filter=status_filter))

    @extend_schema(
        operation_id="catalog_partner_applications_retrieve",
        summary="Retrieve a partner application",
        description="Детальные сведения о заявке на партнёрство и сопоставленная компания.",
        responses={200: DeskPartnerApplicationDetail, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    def retrieve(self, request, pk=None):
        try:
            return Response(service.get_application(int(pk)))
        except AccessError as error:
            return _refused(error)

    @extend_schema(
        operation_id="catalog_partner_applications_send_contract",
        summary="Send contract to applicant",
        description="Переводит заявку в `contract_sent` и опционально сохраняет реквизиты договора.",
        request=DeskPartnerApplicationSendContractIn,
        responses={200: DeskPartnerApplicationDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="send-contract", url_name="send-contract")
    def send_contract(self, request, pk=None):
        body = DeskPartnerApplicationSendContractIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            return Response(service.send_contract(int(pk), dict(body.validated_data), request.user))
        except AccessError as error:
            return _refused(error)

    @extend_schema(
        operation_id="catalog_partner_applications_approve",
        summary="Approve partner application",
        description=(
            "Одобряет заявку, активирует отношение `partner`, фиксирует договор, "
            "связывает компанию с CRM и отправляет приглашение кандидату."
        ),
        request=DeskPartnerApplicationApproveIn,
        responses={200: DeskPartnerApplicationDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="approve", url_name="approve")
    def approve(self, request, pk=None):
        body = DeskPartnerApplicationApproveIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            return Response(service.approve_application(int(pk), dict(body.validated_data), request.user))
        except AccessError as error:
            return _refused(error)

    @extend_schema(
        operation_id="catalog_partner_applications_reject",
        summary="Reject partner application",
        description="Отклоняет заявку с указанием обязательной причины (`rejected_reason`).",
        request=DeskPartnerApplicationRejectIn,
        responses={200: DeskPartnerApplicationDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="reject", url_name="reject")
    def reject(self, request, pk=None):
        body = DeskPartnerApplicationRejectIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            return Response(service.reject_application(int(pk), dict(body.validated_data), request.user))
        except AccessError as error:
            return _refused(error)
