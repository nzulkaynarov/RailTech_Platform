"""Бригады и исполнители услуг (D2-3): `/api/v1/catalog/brigades/`."""

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from catalog.desk import brigades
from catalog.desk.items import ItemError
from catalog.desk.serializers import DeskBrigadeIn, DeskBrigadeRow
from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, PAGE, PAGE_SIZE, REFUSED, SEARCH, DeskViewSet, refuse
from catalog.models import Brigade


class BrigadeDeskViewSet(DeskViewSet):
    """Чтение — любой сотрудник бэк-офиса (без ставки); создание и правка — `catalog.manage`; ставка — ещё и право на ставки."""

    required_permissions = {"create": "catalog.manage", "partial_update": "catalog.manage"}
    lookup_value_regex = r"\d+"
    queryset = Brigade.objects.none()
    serializer_class = DeskBrigadeRow

    def _brigade(self, pk) -> Brigade:
        brigade = Brigade.objects.select_related("currency").filter(pk=pk).first() if str(pk).isdigit() else None
        if brigade is None:
            raise NotFound()
        return brigade

    @extend_schema(
        operation_id="catalog_brigades_list",
        summary="Crews and service performers",
        description="Ставка (`rate`) — `null` без зоны услуг расчёта и без `quote.view_cost_margin`; `rate_visible` говорит, почему.",
        parameters=[
            SEARCH,
            OpenApiParameter("kind", str, enum=Brigade.Kind.values),
            OpenApiParameter("include_inactive", bool, description="Вместе с теми, кто не работает."),
            PAGE,
            PAGE_SIZE,
        ],
        responses={200: DeskBrigadeRow},
        tags=["Catalog"],
    )
    def list(self, request):
        return self.page_of(
            brigades.list_queryset(request.query_params),
            lambda rows: [brigades.brigade_row(b, request.user) for b in rows],
        )

    @extend_schema(
        operation_id="catalog_brigades_create",
        summary="Add a crew or performer",
        description="Needs `catalog.manage`; ставка — ещё и зона услуг или `quote.view_cost_margin` (403 `CREW_RATES_REQUIRED`).",
        request=DeskBrigadeIn,
        responses={201: DeskBrigadeRow, 400: REFUSED, 403: FORBIDDEN},
        tags=["Catalog"],
    )
    def create(self, request):
        body = DeskBrigadeIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                brigade = brigades.save_brigade(Brigade(), dict(body.validated_data), request.user)
        except ItemError as error:
            return refuse(error)
        return Response(brigades.brigade_row(brigade, request.user), status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="catalog_brigades_update",
        summary="Edit a crew or performer",
        description="Needs `catalog.manage`; ставка — ещё и зона услуг или `quote.view_cost_margin` (403 `CREW_RATES_REQUIRED`). `is_active=false` убирает из выбора.",
        request=DeskBrigadeIn,
        responses={200: DeskBrigadeRow, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Catalog"],
    )
    def partial_update(self, request, pk=None):
        brigade = self._brigade(pk)
        body = DeskBrigadeIn(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                brigades.save_brigade(brigade, dict(body.validated_data), request.user)
        except ItemError as error:
            return refuse(error)
        return Response(brigades.brigade_row(brigade, request.user))
