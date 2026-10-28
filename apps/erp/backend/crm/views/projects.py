"""Проекты (D2-5): `GET /crm/projects/` и `GET /crm/projects/{id}/` — только чтение, только сотрудник компании-владельца.

Список и карточку собирает `crm/services/projects.py`; доступные действия по договору и акту в карточке считает сервер из
статуса и прав зрителя. Не сотрудник (покупатель, посторонний) — 403 `PROJECT_STAFF_ONLY`; сделка вне проектов или
несуществующая — 404 `NOT_FOUND`, существование не раскрывается.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm.serializers.projects import ProjectCardSerializer, ProjectPageSerializer
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
            OpenApiParameter("deal_id", int, description="Одна сделка (точный поиск по номеру ПР)"),
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
