"""`/api/v1/catalog/partner-applications/` — очередь заявок кандидатов в партнёры (PART-ONBOARD-2).

Чтение — любой сотрудник бэк-офиса, действия договорного шлюза (отправка договора, одобрение,
отклонение) — `supply.manage`.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from parties.models import PartnerApplication
from portal.desk import service_partner_applications as service
from django.http import HttpResponse
from portal.desk import service_partner_contract as contract_step
from portal.desk.serializers import (
    DeskPartnerApplicationApproveIn,
    DeskPartnerApplicationCreateIn,
    DeskPartnerApplicationDetail,
    DeskPartnerApplicationListResponse,
    DeskPartnerApplicationRejectIn,
    DeskPartnerContractDecisionIn,
    DeskPartnerContractOptions,
    DeskPartnerContractPrepareIn,
    DeskPartnerApplicationSendContractIn,
)
from portal.desk.service import AccessError
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, REFUSED, DeskViewSet

SUPPLY_MANAGE = "supply.manage"


def _refused(error: AccessError) -> Response:
    return Response({"detail": error.code}, status=error.status)


class PartnerApplicationDeskViewSet(DeskViewSet):
    required_permissions = {
        "create": SUPPLY_MANAGE,
        "send_contract": SUPPLY_MANAGE,
        "prepare_contract": SUPPLY_MANAGE,
        # Решает держатель зоны «Право»; тот же код права проверяет сервис (ДОК-10)
        "contract_decision": "contract.approve_template",
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
        return Response(service.list_applications(status_filter=status_filter, viewer=request.user))

    @extend_schema(
        operation_id="catalog_partner_applications_create",
        summary="Create a partner application from an incoming letter",
        description=(
            "План 1.9, «Передать в работу»: сотрудник снабжения заводит заявку кандидата по входящему письму "
            "(`source = letter`, `source_ref` — номер входящего письма). Согласия кандидата нет — дальше договорный шлюз."
        ),
        request=DeskPartnerApplicationCreateIn,
        responses={201: DeskPartnerApplicationDetail, 400: REFUSED, 403: FORBIDDEN},
        tags=["Catalog"],
    )
    def create(self, request):
        body = DeskPartnerApplicationCreateIn(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(service.create_from_letter(dict(body.validated_data), request.user), status=201)

    @extend_schema(
        operation_id="catalog_partner_applications_retrieve",
        summary="Retrieve a partner application",
        description="Детальные сведения о заявке на партнёрство и сопоставленная компания.",
        responses={200: DeskPartnerApplicationDetail, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    def retrieve(self, request, pk=None):
        try:
            return Response(service.get_application(int(pk), request.user))
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

    @extend_schema(
        operation_id="catalog_partner_applications_contract_options",
        summary="Templates to prepare the partner contract from",
        description=(
            "Утверждённые шаблоны вида «партнёр» из библиотеки (по умолчанию — из настроек компании), языки каждого, "
            "правило отступлений и кто решает. Пустой список — договор можно подготовить только своим файлом."
        ),
        responses={200: DeskPartnerContractOptions},
        tags=["Catalog"],
    )
    @action(detail=False, methods=["get"], url_path="contract-options", url_name="contract-options")
    def contract_options(self, request):
        return Response(contract_step.contract_options(request.user))

    @extend_schema(
        operation_id="catalog_partner_applications_prepare_contract",
        summary="Prepare the partner contract",
        description=(
            "Договор из утверждённого шаблона либо свой файл (multipart, `file`). Шаблон без отступлений готов к отправке; "
            "свой файл или текст отступления уходят на решение держателя «Право»."
        ),
        request=DeskPartnerContractPrepareIn,
        responses={200: DeskPartnerApplicationDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="prepare-contract",
        url_name="prepare-contract",
        parser_classes=[MultiPartParser, JSONParser],
    )
    def prepare_contract(self, request, pk=None):
        body = DeskPartnerContractPrepareIn(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        upload = data.pop("file", None)
        try:
            contract_step.prepare_contract(int(pk), data, upload, request.user)
            return Response(service.get_application(int(pk), request.user))
        except AccessError as error:
            return _refused(error)

    @extend_schema(
        operation_id="catalog_partner_applications_contract_decision",
        summary="Decide on the partner contract",
        description="Решение держателя права утверждать договоры: `approve` или `return` (замечание обязательно).",
        request=DeskPartnerContractDecisionIn,
        responses={200: DeskPartnerApplicationDetail, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["post"], url_path="contract-decision", url_name="contract-decision")
    def contract_decision(self, request, pk=None):
        body = DeskPartnerContractDecisionIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            contract_step.decide_contract(int(pk), dict(body.validated_data), request.user)
            return Response(service.get_application(int(pk), request.user))
        except AccessError as error:
            return _refused(error)

    @extend_schema(
        operation_id="catalog_partner_applications_document",
        summary="Download the contract or the signed scan",
        description="`which=contract` — договор, который видит кандидат; `which=scan` — скан подписанного.",
        parameters=[OpenApiParameter("which", str, required=True, enum=["contract", "scan"])],
        responses={(200, "application/octet-stream"): bytes, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    @action(detail=True, methods=["get"], url_path="document", url_name="document")
    def document(self, request, pk=None):
        app = PartnerApplication.objects.filter(pk=pk).first()
        if app is None:
            return Response({"detail": "NOT_FOUND"}, status=404)
        which = request.query_params.get("which", "contract")
        field = app.signed_scan if which == "scan" else contract_step.current_document(app)
        try:
            data, content_type, name = contract_step.read_file(field)
        except AccessError as error:
            return _refused(error)
        response = HttpResponse(data, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response
