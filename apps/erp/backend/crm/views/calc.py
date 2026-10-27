"""Расчёт по заявке для Платформы (D2-1, SPEC-v3 §7.4): `/api/v1/calc/*`.

Тонкие обёртки (CONVENTIONS.md §5, Rule 8): проверить тело → вызвать одну функцию `crm.services.calculation` → вернуть.
Право на мутацию объявлено на вьюхе (`RoleGatedViewMixin`), зону строки и прочие правила решает сервис; отказ сервиса —
`{"detail": "<CODE>"}` со статусом из `CalcError`.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import RoleGatedViewMixin

from ..serializers.calc import (
    CalcCatalogSerializer,
    CalcErrorSerializer,
    CalcJobSerializer,
    CalcLinePatchSerializer,
    CalcLinesCreatedSerializer,
    CalcLinesInSerializer,
    CalcParseInSerializer,
    CalcSheetSerializer,
    CalcTaskListSerializer,
)
from ..services import calculation as calc
from ..services.calculation import CalcError, LineInput

TAGS = ["Calc"]
ERRORS = {
    400: OpenApiResponse(CalcErrorSerializer, description="Тело не прошло проверку или отказ правила строки"),
    403: OpenApiResponse(CalcErrorSerializer, description="Нет права (зона строки, роль) или не сотрудник"),
    404: OpenApiResponse(CalcErrorSerializer, description="Заявки, задания расчёта или строки нет"),
    409: OpenApiResponse(
        CalcErrorSerializer, description="Состояние не позволяет (КП не черновик, нет виз, ИИ выключен)"
    ),
}
READ_ERRORS = {403: ERRORS[403], 404: ERRORS[404]}
VISA_ZONES = ("quote.visa_goods", "quote.visa_services")


def _fail(exc: CalcError) -> Response:
    return Response({"detail": exc.code, **exc.extra}, status=exc.status)


def _invalid(serializer) -> Response:
    return Response({"detail": "VALIDATION_FAILED", **serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class CalcTaskListView(APIView):
    """GET /api/v1/calc/tasks/ — «Заявки в расчёте» (и «Мои расчёты» с `mine=1`)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="calc_tasks_list",
        summary="Заявки с заданием расчёта",
        tags=TAGS,
        parameters=[
            OpenApiParameter("mine", bool, description="Только где сотрудник — исполнитель резолюции"),
            OpenApiParameter("scope", str, enum=["open", "all"], description="open — стадии расчёта; all — все"),
        ],
        responses={200: CalcTaskListSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        mine = str(request.query_params.get("mine", "")).lower() in ("1", "true", "yes")
        scope = "all" if request.query_params.get("scope") == "all" else "open"
        try:
            rows = calc.list_tasks(request.user, mine=mine, scope=scope)
        except CalcError as exc:
            return _fail(exc)
        return Response({"results": rows})


class CalcSheetView(APIView):
    """GET /api/v1/calc/<deal_id>/ — экран расчёта по заявке."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="calc_sheet",
        summary="Расчёт по заявке",
        tags=TAGS,
        responses={200: CalcSheetSerializer, **READ_ERRORS},
    )
    def get(self, request, deal_id: int):
        try:
            return Response(calc.sheet(deal_id, request.user))
        except CalcError as exc:
            return _fail(exc)


class CalcStartView(RoleGatedViewMixin, APIView):
    """POST /api/v1/calc/<deal_id>/start/ — черновик КП расчёта из строк заявки (повтор — без изменений)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "quote.build"}

    @extend_schema(
        operation_id="calc_start",
        summary="Начать расчёт: черновик КП из строк заявки",
        tags=TAGS,
        request=None,
        responses={200: CalcSheetSerializer, **ERRORS},
    )
    def post(self, request, deal_id: int):
        try:
            return Response(calc.start(deal_id, request.user))
        except CalcError as exc:
            return _fail(exc)


class CalcLinesView(RoleGatedViewMixin, APIView):
    """POST /api/v1/calc/<deal_id>/lines/ — добавить строки (вручную или подтверждённое предложение ИИ-разбора)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "quote.build"}

    @extend_schema(
        operation_id="calc_lines_add",
        summary="Добавить строки в расчёт",
        tags=TAGS,
        request=CalcLinesInSerializer,
        responses={201: CalcLinesCreatedSerializer, **ERRORS},
    )
    def post(self, request, deal_id: int):
        serializer = CalcLinesInSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        rows = [LineInput(**row) for row in serializer.validated_data["lines"]]
        try:
            return Response(calc.add_lines(deal_id, request.user, rows), status=status.HTTP_201_CREATED)
        except CalcError as exc:
            return _fail(exc)


class CalcLineView(RoleGatedViewMixin, APIView):
    """PATCH/DELETE /api/v1/calc/<deal_id>/lines/<item_id>/ — правка и удаление строки (зона строки — в сервисе)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"PATCH": "quote.build", "DELETE": "quote.build"}

    @extend_schema(
        operation_id="calc_line_update",
        summary="Изменить строку расчёта (виза строки снимается)",
        tags=TAGS,
        request=CalcLinePatchSerializer,
        responses={200: CalcSheetSerializer, **ERRORS},
    )
    def patch(self, request, deal_id: int, item_id: int):
        serializer = CalcLinePatchSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            return Response(calc.update_line(deal_id, item_id, request.user, dict(serializer.validated_data)))
        except CalcError as exc:
            return _fail(exc)

    @extend_schema(
        operation_id="calc_line_delete",
        summary="Удалить строку расчёта",
        tags=TAGS,
        responses={200: CalcSheetSerializer, **ERRORS},
    )
    def delete(self, request, deal_id: int, item_id: int):
        try:
            return Response(calc.delete_line(deal_id, item_id, request.user))
        except CalcError as exc:
            return _fail(exc)


class CalcLineVisaView(RoleGatedViewMixin, APIView):
    """POST /api/v1/calc/<deal_id>/lines/<item_id>/visa/ — «Подтвердить» строку (право зоны строки)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": VISA_ZONES}

    @extend_schema(
        operation_id="calc_line_sign",
        summary="Виза строки расчёта по её зоне",
        tags=TAGS,
        request=None,
        responses={200: CalcSheetSerializer, **ERRORS},
    )
    def post(self, request, deal_id: int, item_id: int):
        try:
            return Response(calc.sign_line(deal_id, item_id, request.user))
        except CalcError as exc:
            return _fail(exc)


class CalcReadyView(RoleGatedViewMixin, APIView):
    """POST /api/v1/calc/<deal_id>/ready/ — «Расчёт готов → черновик КП директору»."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "quote.build"}

    @extend_schema(
        operation_id="calc_ready",
        summary="Расчёт готов: КП на одобрение директору (все строки завизированы)",
        tags=TAGS,
        request=None,
        responses={200: CalcSheetSerializer, **ERRORS},
    )
    def post(self, request, deal_id: int):
        try:
            return Response(calc.mark_ready(deal_id, request.user))
        except CalcError as exc:
            return _fail(exc)
        except ValueError as exc:  # request_director_approval: КП без клиента
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)


class CalcParseView(RoleGatedViewMixin, APIView):
    """POST /api/v1/calc/<deal_id>/parse/ — ИИ-разбор текста заявки в строки: задание в очереди ИИ, ответ — предложение
    (`GET /api/v1/sourcing/ai-status/<task_id>/`, результат `{proposal: [...]}`); строки не пишутся."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": "quote.build"}

    @extend_schema(
        operation_id="calc_parse",
        summary="ИИ-разбор текста заявки в строки (предложение)",
        tags=TAGS,
        request=CalcParseInSerializer,
        responses={
            202: CalcJobSerializer,
            429: OpenApiResponse(CalcErrorSerializer, description="Дневной лимит ИИ компании"),
            500: OpenApiResponse(CalcErrorSerializer, description="Очередь ИИ недоступна"),
            **ERRORS,
        },
    )
    def post(self, request, deal_id: int):
        from django.conf import settings

        from sourcing.ai_jobs import enqueue_ai_job

        serializer = CalcParseInSerializer(data=request.data)
        if not serializer.is_valid():
            return _invalid(serializer)
        try:
            payload = calc.parse_payload(deal_id, request.user, serializer.validated_data.get("text"))
        except CalcError as exc:
            return _fail(exc)
        if not getattr(settings, "AI_IMPORT_ENABLED", False):
            # Выключенный ИИ — состояние настроек компании, а не сбой сервиса: 409 (BFF не путает его с «ERP недоступна»).
            return Response({"detail": "AI_DISABLED"}, status=status.HTTP_409_CONFLICT)
        return enqueue_ai_job("calc_parse_text", payload, request.user)


class CalcCatalogView(APIView):
    """GET /api/v1/calc/catalog/?q= — карточки каталога для сопоставления строки (без ИИ)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="calc_catalog_search",
        summary="Каталог для сопоставления строки расчёта",
        tags=TAGS,
        parameters=[OpenApiParameter("q", str, description="Слова названия, артикула, кода производителя, ГОСТ")],
        responses={200: CalcCatalogSerializer, 403: ERRORS[403]},
    )
    def get(self, request):
        try:
            rows = calc.catalog_search(request.user, request.query_params.get("q", "")[:200])
        except CalcError as exc:
            return _fail(exc)
        return Response({"results": rows})
