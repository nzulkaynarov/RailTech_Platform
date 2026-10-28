"""Общая основа вьюх D2-3: сотрудник бэк-офиса читает, запись — по праву роли (`RoleGatedViewMixin`), отказы — `{"detail": КОД}`."""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

from catalog.desk.items import ItemError
from core.pagination import DefaultPageNumberPagination
from core.permissions import IsBackOfficeStaff, RoleGatedViewMixin

#: Отказы по праву на закрытое поле: 403, а не ошибка проверки.
FORBIDDEN_CODES = frozenset({"SUPPLIER_PRICES_REQUIRED", "CREW_RATES_REQUIRED"})
CONFLICT_CODES = frozenset({"HS_CODE_EXISTS"})

SEARCH = OpenApiParameter("q", str, description="Поиск по названию и коду.")
PAGE = OpenApiParameter("page", int, description="Номер страницы.")
PAGE_SIZE = OpenApiParameter("page_size", int, description="Строк на странице, до 200.")

FORBIDDEN = OpenApiResponse(
    description="Нет права роли (`ROLE_NOT_PERMITTED`) или закрытое поле (`SUPPLIER_PRICES_REQUIRED`, `CREW_RATES_REQUIRED`)."
)
REFUSED = OpenApiResponse(description="Отказ проверки: код в `detail` или ошибки полей.")
NOT_FOUND = OpenApiResponse(description="Объекта нет.")


def refuse(error: ItemError) -> Response:
    if error.code in FORBIDDEN_CODES:
        code = status.HTTP_403_FORBIDDEN
    elif error.code in CONFLICT_CODES:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return Response({"detail": error.code}, status=code)


class DeskViewSet(RoleGatedViewMixin, viewsets.GenericViewSet):
    """Чтение — любой сотрудник бэк-офиса своей компании; мутации — `required_permissions` вьюхи (закрыты, пока не объявлены)."""

    permission_classes = [permissions.IsAuthenticated, IsBackOfficeStaff]
    pagination_class = DefaultPageNumberPagination

    def page_of(self, queryset, build):
        """Страница `{count, next, previous, results}`; `build(page_rows)` превращает строки модели в словари."""
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(build(page))
