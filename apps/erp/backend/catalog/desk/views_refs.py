"""Справочники для Платформы (D2-3, B-035): коды ТН ВЭД `/api/v1/master-data/hs-codes/` и курсы `/api/v1/exchange-rates/`."""

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from catalog.desk import refs
from catalog.desk.items import ItemError
from catalog.desk.serializers import DeskExchangeRate, DeskHsCode, DeskHsCodeIn
from catalog.desk.views_base import FORBIDDEN, NOT_FOUND, PAGE, PAGE_SIZE, REFUSED, SEARCH, DeskViewSet, refuse
from catalog.models import HSCode
from core.models import ExchangeRate


class HsCodeDeskViewSet(DeskViewSet):
    """Классификатор ТН ВЭД: чтение — любой сотрудник; добавить код и править наименование и срок — `catalog.manage`.
    Код выведенный из обращения не удаляется, а закрывается датой (`valid_until`)."""

    required_permissions = {"create": "catalog.manage", "partial_update": "catalog.manage"}
    queryset = HSCode.objects.none()
    serializer_class = DeskHsCode
    lookup_value_regex = r"\d+"

    @extend_schema(
        operation_id="master_data_hs_codes_list",
        summary="HS (TN VED) code classifier",
        parameters=[
            SEARCH,
            OpenApiParameter("level", int, enum=list(refs.HS_LEVELS), description="Число знаков кода."),
            OpenApiParameter("active", bool, description="Только действующие на сегодня."),
            PAGE,
            PAGE_SIZE,
        ],
        responses={200: DeskHsCode},
        tags=["Master Data"],
    )
    def list(self, request):
        return self.page_of(refs.hs_queryset(request.query_params), lambda rows: [refs.hs_row(c) for c in rows])

    @extend_schema(
        operation_id="master_data_hs_codes_create",
        summary="Add an HS code",
        description="Needs `catalog.manage`. Код — 2, 4, 6, 8 или 10 цифр; повтор — 409 `HS_CODE_EXISTS`. Родитель находится по самому длинному существующему префиксу.",
        request=DeskHsCodeIn,
        responses={
            201: DeskHsCode,
            400: REFUSED,
            403: FORBIDDEN,
            409: OpenApiResponse(description="HS_CODE_EXISTS — такой код уже есть."),
        },
        tags=["Master Data"],
    )
    def create(self, request):
        body = DeskHsCodeIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                code = refs.create_hs(dict(body.validated_data))
        except ItemError as error:
            return refuse(error)
        return Response(refs.hs_row(code), status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="master_data_hs_codes_update",
        summary="Edit an HS code",
        description="Needs `catalog.manage`. Менять можно наименование, единицы и срок действия; сам код — нет.",
        request=DeskHsCodeIn,
        responses={200: DeskHsCode, 400: REFUSED, 403: FORBIDDEN, 404: NOT_FOUND},
        tags=["Master Data"],
    )
    def partial_update(self, request, pk=None):
        code = HSCode.objects.filter(pk=pk).first()
        if code is None:
            raise NotFound()
        body = DeskHsCodeIn(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        data = {k: v for k, v in body.validated_data.items() if k != "code"}
        try:
            with transaction.atomic():
                refs.update_hs(code, data)
        except ItemError as error:
            return refuse(error)
        return Response(refs.hs_row(code))


class ExchangeRateListViewSet(DeskViewSet):
    """Строки справочника курсов к UZS (источник ЦБ или вручную); ввод курса на дату — `exchange-rates/manual/`."""

    required_permissions = {}
    queryset = ExchangeRate.objects.none()
    serializer_class = DeskExchangeRate

    @extend_schema(
        operation_id="exchange_rates_list",
        summary="Exchange rate rows",
        description="Курсы к UZS по дням, новые первыми. Читает любой сотрудник; ручной ввод — `settings.edit` (`POST exchange-rates/manual/`).",
        parameters=[OpenApiParameter("currency", str, description="Код валюты (USD, EUR, RUB)."), PAGE, PAGE_SIZE],
        responses={200: DeskExchangeRate},
        tags=["Finance"],
    )
    def list(self, request):
        return self.page_of(refs.rates_queryset(request.query_params), lambda rows: [refs.rate_row(r) for r in rows])
