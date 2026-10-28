"""Действия сотрудника по договору и акту без подписи кликом (D2-5, SPEC-v3 §2.4): подмешиваются во вьюсеты биллинга.

Договор: `send-to-client`, `client-agreed`, `reject`, `revise`, `mark-issued`, `attach-scan` — переходы
`crm/services/contract_flow.py`. Акт: `attach-scan`, `record-return` — `crm/services/act_flow.py`. Объект берётся
`self.get_object()` (сужение по видимости и объектные права DRF), право на действие объявлено во вьюсете
(`required_permissions`) и проверяется ещё раз сервисом. Ошибка — `{"detail": "<CODE>"}` с кодом статуса из `_HTTP`.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from crm.serializers.projects import (
    ActFlowSerializer,
    ActReturnInSerializer,
    ActScanInSerializer,
    ContractFlowSerializer,
    ContractScanInSerializer,
    ContractTransitionInSerializer,
)
from crm.services import act_flow, contract_flow
from crm.views.request_body import invalid_body_response, is_object_body

_HTTP = {
    "CONTRACT_NOT_FOUND": 404,
    "MEMBER_REQUIRED_FOR_ACTION": 403,
    "CONTRACT_TRANSITION_NOT_ALLOWED": 409,
    "ACT_SIGN_NOT_ALLOWED": 409,
}
_ERRORS = {
    400: OpenApiResponse(description="REASON_REQUIRED / SCAN_REQUIRED / SCAN_INVALID / NO_FILE_PROVIDED"),
    403: OpenApiResponse(description="MEMBER_REQUIRED_FOR_ACTION / ROLE_NOT_PERMITTED"),
    404: OpenApiResponse(description="Не найдено"),
    409: OpenApiResponse(description="CONTRACT_TRANSITION_NOT_ALLOWED / ACT_SIGN_NOT_ALLOWED: статус не тот"),
}


def _fail(error: str) -> Response:
    return Response({"detail": error}, status=_HTTP.get(error, 400))


class ContractFlowMixin:
    """Переходы статусов договора (`contract_flow.TRANSITIONS`)."""

    def _transition(self, request, pk, name: str, *, with_file: bool = False):
        contract = self.get_object()  # видимость и объектные права — до сервиса
        if not is_object_body(request):
            return invalid_body_response()
        body = (
            ContractScanInSerializer(data=request.data)
            if with_file
            else ContractTransitionInSerializer(data=request.data)
        )
        if not body.is_valid():
            return Response({"detail": "NO_FILE_PROVIDED" if with_file else "VALIDATION_FAILED"}, status=400)
        data = body.validated_data
        updated, error = contract_flow.apply_transition(
            contract.id,
            name,
            request.user,
            reason=data.get("reason", ""),
            note=data.get("note", ""),
            scan=data.get("file"),
        )
        if error:
            return _fail(error)
        return Response(ContractFlowSerializer(updated, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Отправить проект договора клиенту на согласование редакции (DRAFT → PENDING_CLIENT)",
        request=ContractTransitionInSerializer,
        responses={200: ContractFlowSerializer, **_ERRORS},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="send-to-client")
    def send_to_client(self, request, pk=None):
        return self._transition(request, pk, "send_to_client")

    @extend_schema(
        summary="Отметить: редакция согласована клиентом (PENDING_CLIENT → PENDING_MANAGER)",
        request=ContractTransitionInSerializer,
        responses={200: ContractFlowSerializer, **_ERRORS},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="client-agreed")
    def client_agreed(self, request, pk=None):
        return self._transition(request, pk, "client_agreed")

    @extend_schema(
        summary="Записать отклонение договора клиентом (→ REJECTED), причина обязательна",
        request=ContractTransitionInSerializer,
        responses={200: ContractFlowSerializer, **_ERRORS},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._transition(request, pk, "reject")

    @extend_schema(
        summary="Вернуть отклонённый проект договора в работу (REJECTED → DRAFT)",
        request=ContractTransitionInSerializer,
        responses={200: ContractFlowSerializer, **_ERRORS},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="revise")
    def revise(self, request, pk=None):
        return self._transition(request, pk, "revise")

    @extend_schema(
        summary="Отметить: договор выставлен у оператора ЭДО (PENDING_MANAGER → ISSUED_EXTERNAL)",
        request=ContractTransitionInSerializer,
        responses={200: ContractFlowSerializer, **_ERRORS},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="mark-issued")
    def mark_issued(self, request, pk=None):
        return self._transition(request, pk, "mark_issued")

    @extend_schema(
        summary="Прикрепить скан подписанного договора (ISSUED_EXTERNAL → SIGNED)",
        description=(
            "PDF или изображение (jpg, png, webp) до 20 МБ; сигнатура байтов должна совпадать с расширением. Договор "
            "становится «Подписан», сделка уходит в `CLOSED_WON` — задача создаёт черновик счёта на предоплату."
        ),
        request={"multipart/form-data": ContractScanInSerializer},
        responses={200: ContractFlowSerializer, **_ERRORS},
        tags=["CRM"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="attach-scan",
        parser_classes=[MultiPartParser, FormParser],
    )
    def attach_scan(self, request, pk=None):
        return self._transition(request, pk, "attach_scan", with_file=True)


class ActFlowMixin:
    """Скан подписанного акта и возврат, записанные сотрудником (`act_flow`)."""

    @extend_schema(
        summary="Прикрепить скан подписанного акта (ISSUED → SIGNED)",
        description="PDF или изображение (jpg, png, webp) до 20 МБ. Акт становится «Подписан (скан)»; публикуется `act.accepted`.",
        request={"multipart/form-data": ActScanInSerializer},
        responses={200: ActFlowSerializer, **_ERRORS},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="attach-scan", parser_classes=[MultiPartParser, FormParser])
    def attach_scan(self, request, pk=None):
        act = self.get_object()
        body = ActScanInSerializer(data=request.data)
        if not body.is_valid():
            return Response({"detail": "NO_FILE_PROVIDED"}, status=400)
        updated, error = act_flow.attach_act_scan(act.id, request.user, body.validated_data["file"])
        if error:
            return _fail(error)
        return Response(ActFlowSerializer(updated, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Записать возврат акта заказчиком (ISSUED → DRAFT с причиной)",
        request=ActReturnInSerializer,
        responses={200: ActFlowSerializer, **_ERRORS},
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="record-return")
    def record_return(self, request, pk=None):
        act = self.get_object()
        if not is_object_body(request):
            return invalid_body_response()
        body = ActReturnInSerializer(data=request.data)
        if not body.is_valid():
            return Response({"detail": "REASON_REQUIRED"}, status=400)
        updated, error = act_flow.record_act_return(act.id, request.user, body.validated_data["reason"])
        if error:
            return _fail(error)
        return Response(ActFlowSerializer(updated, context=self.get_serializer_context()).data)


__all__ = ["ActFlowMixin", "ContractFlowMixin"]
