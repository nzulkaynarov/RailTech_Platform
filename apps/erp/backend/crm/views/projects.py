"""Проекты (D2-5): `GET /crm/projects/` и `GET /crm/projects/{id}/` — только чтение, только сотрудник компании-владельца.

Список и карточку собирает `crm/services/projects.py`; доступные действия по договору и акту в карточке считает сервер из
статуса и прав зрителя. Не сотрудник (покупатель, посторонний) — 403 `PROJECT_STAFF_ONLY`; сделка вне проектов или
несуществующая — 404 `NOT_FOUND`, существование не раскрывается.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import RoleGatedViewMixin
from crm.serializers.projects import DeliveryMarkInSerializer, ProjectCardSerializer, ProjectPageSerializer
from crm.services import projects

PAGE_MAX = 100


class IsProjectReader(BasePermission):
    """Сотрудник своей компании или администратор; клиентских аккаунтов в ERP нет (FIX-13)."""

    message = "PROJECT_STAFF_ONLY"

    def has_permission(self, request, view):
        return projects.is_staff_reader(request.user)


def _int(value, default: int, *, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


class ProjectListView(APIView):
    """Проекты: сделки с принятым КП, их договор, счета, акт и исполнение (SPEC-v3 §7.3)."""

    permission_classes = [IsAuthenticated, IsProjectReader]

    @extend_schema(
        operation_id="crm_projects_list",
        summary="Проекты: список",
        description=(
            "Сделки от принятия КП клиентом. Шаг (`CONTRACT`/`PAYMENT`/`DONE`), статус для клиента и «проблемы» выводятся "
            "из документов. Порядок — от новых; страница — `limit`/`offset`. Читает сотрудник компании-владельца."
        ),
        parameters=[
            OpenApiParameter("q", str, description="Название, клиент, номер КП, договора, счёта или акта"),
            OpenApiParameter("mine", bool, description="Только проекты, где сотрудник — менеджер или взявший в работу"),
            OpenApiParameter(
                "problems", bool, description="Только с проблемами: договор отклонён, акт возвращён, счёт просрочен"
            ),
            OpenApiParameter("step", str, enum=["CONTRACT", "PAYMENT", "DONE"], description="Шаг пути заявки"),
            OpenApiParameter("deal_id", int, description="Одна сделка по id"),
            OpenApiParameter("number", str, description="Одна сделка по номеру (год и NNN, префикс не важен)"),
            OpenApiParameter("limit", int, description="Размер страницы, 1–100 (по умолчанию 25)"),
            OpenApiParameter("offset", int, description="Сдвиг"),
        ],
        responses={
            200: ProjectPageSerializer,
            403: OpenApiResponse(description="PROJECT_STAFF_ONLY"),
        },
        tags=["CRM"],
    )
    def get(self, request):
        params = request.query_params
        step = params.get("step", "")
        filters = projects.Filters(
            q=params.get("q", ""),
            mine=str(params.get("mine", "")).lower() in ("1", "true"),
            problems=str(params.get("problems", "")).lower() in ("1", "true"),
            step=step if step in projects.STEPS else "",
            deal_id=_int(params.get("deal_id"), 0, low=0, high=2**31 - 1) or None,
            number=params.get("number", "")[:64],
        )
        rows, total = projects.list_projects(
            request.user,
            filters,
            limit=_int(params.get("limit"), 25, low=1, high=PAGE_MAX),
            offset=_int(params.get("offset"), 0, low=0, high=10**6),
        )
        return Response(ProjectPageSerializer({"count": total, "results": rows}).data)


class ProjectDetailView(APIView):
    """Карточка проекта по сделке."""

    permission_classes = [IsAuthenticated, IsProjectReader]

    @extend_schema(
        operation_id="crm_projects_retrieve",
        summary="Проект: карточка",
        description=(
            "Документы проекта (КП, договор, счета, акт) с историей и действиями, доступными ЭТОМУ сотруднику, исполнение "
            "(отгрузка и строки поставки — только чтение) и журнал документов."
        ),
        parameters=[
            OpenApiParameter("deal_id", int, OpenApiParameter.PATH, description="Сделка ERP (`deal_id` строки списка)")
        ],
        responses={
            200: ProjectCardSerializer,
            403: OpenApiResponse(description="PROJECT_STAFF_ONLY"),
            404: OpenApiResponse(description="NOT_FOUND: сделки нет или она не проект"),
        },
        tags=["CRM"],
    )
    def get(self, request, deal_id):
        deal = projects.project_for_user(request.user, deal_id)
        if deal is None:
            raise NotFound("NOT_FOUND")
        return Response(ProjectCardSerializer(projects.project_card(deal, request.user)).data)


class ProjectDeliveryView(RoleGatedViewMixin, APIView):
    """Отметка доставки клиенту по проекту (L0-1): «Отправлено клиенту / В пути» или «Доставлено».

    Тонкая обёртка (CONVENTIONS.md §5): право `fulfillment.manage` объявлено здесь (`required_permissions`), поля, файл,
    переход и смена статуса — `sales.services.delivery_progress`.
    """

    permission_classes = [IsAuthenticated, IsProjectReader]
    parser_classes = [MultiPartParser, FormParser]
    required_permissions = {"POST": "fulfillment.manage"}

    @extend_schema(
        operation_id="crm_projects_delivery_create",
        summary="Проект: отметить доставку — «В пути» или «Доставлено»",
        description=(
            "Отметка на весь проект (исполнение сделки одно): `in_transit` — из «Ожидает отгрузки» и «Отгружено», "
            "`delivered` — из них же и из «В пути». Дата — не позже сегодня, доставка — не раньше отправки; № накладной "
            "перевозчика и файл подтверждения (изображение, PDF, doc, docx, xls, xlsx, csv, txt до 20 МБ) — по желанию. "
            "Смена статуса — сервис исполнения (накладная, события `delivery.status_changed`, уведомления); строки поставки "
            "получают статус сразу, клиент принимает доставленное в кабинете. Право `fulfillment.manage`."
        ),
        parameters=[OpenApiParameter("deal_id", int, OpenApiParameter.PATH, description="Сделка ERP")],
        request={"multipart/form-data": DeliveryMarkInSerializer},
        responses={
            200: ProjectCardSerializer,
            400: OpenApiResponse(
                description=(
                    "DELIVERY_ACTION_INVALID / DELIVERY_DATE_INVALID / DELIVERY_DATE_IN_FUTURE / "
                    "DELIVERY_DATE_BEFORE_SHIPPED / WAYBILL_TOO_LONG / PROOF_INVALID"
                )
            ),
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED / PROJECT_STAFF_ONLY"),
            404: OpenApiResponse(description="NOT_FOUND: сделки нет или она не проект"),
            409: OpenApiResponse(description="FULFILLMENT_NOT_READY / DELIVERY_TRANSITION_NOT_ALLOWED"),
        },
        tags=["CRM"],
    )
    def post(self, request, deal_id):
        from sales.services.delivery_progress import HTTP_STATUS, DeliveryMark, mark_delivery

        if projects.project_for_user(request.user, deal_id) is None:
            raise NotFound("NOT_FOUND")
        data = request.data

        def text(name: str) -> str:
            value = data.get(name)
            return value if isinstance(value, str) else ""

        mark = DeliveryMark(
            action=text("action"), on_date=text("on_date"), waybill=text("waybill"), proof=request.FILES.get("file")
        )
        _fulfillment, error = mark_delivery(deal_id, request.user, mark)
        if error:
            return Response({"detail": error}, status=HTTP_STATUS.get(error, 400))
        deal = projects.project_for_user(request.user, deal_id)
        return Response(ProjectCardSerializer(projects.project_card(deal, request.user)).data)
