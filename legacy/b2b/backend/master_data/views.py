from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from core.permissions import IsPlatformAdminOrReadOnly

from .models import Country, Currency, DeliveryBasis, HSCode, UnitOfMeasure
from .serializers import CountrySerializer, CurrencySerializer, DeliveryBasisSerializer, UnitOfMeasureSerializer

LOOKUP_CACHE_TTL = 60 * 10  # 10 min — master data changes rarely


class _ActiveOnlyListMixin:
    """Selection dropdowns must show only ACTIVE lookups, so deactivating a row in
    admin hides it everywhere (consistent with how services query the справочник,
    e.g. AI unit validation filters is_active=True). Applied to `list` only — so the
    response is identical for every caller (the list is cache_page-cached and does
    NOT vary on auth) while retrieve/update/destroy keep the full queryset so an admin
    can still manage (and reactivate) an inactive row by id."""

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self, "action", None) == "list":
            qs = qs.filter(is_active=True)
        return qs


@extend_schema_view(
    list=extend_schema(summary="List countries", tags=["Master Data"]),
    create=extend_schema(summary="Create country", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get country", tags=["Master Data"]),
    update=extend_schema(summary="Update country", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update country", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete country", tags=["Master Data"]),
)
@method_decorator(vary_on_headers("Accept-Language"), name="list")
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name="list")
class CountryViewSet(_ActiveOnlyListMixin, viewsets.ModelViewSet):
    """CRUD for countries (read: public; write: admin)."""

    queryset = Country.objects.all().order_by("sort_order", "name")
    serializer_class = CountrySerializer
    permission_classes = [IsPlatformAdminOrReadOnly]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(summary="List currencies", tags=["Master Data"]),
    create=extend_schema(summary="Create currency", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get currency", tags=["Master Data"]),
    update=extend_schema(summary="Update currency", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update currency", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete currency", tags=["Master Data"]),
)
@method_decorator(vary_on_headers("Accept-Language"), name="list")
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name="list")
class CurrencyViewSet(_ActiveOnlyListMixin, viewsets.ModelViewSet):
    """CRUD for currencies (read: public; write: admin)."""

    queryset = Currency.objects.all().order_by("sort_order", "code")
    serializer_class = CurrencySerializer
    permission_classes = [IsPlatformAdminOrReadOnly]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(summary="List units of measure", tags=["Master Data"]),
    create=extend_schema(summary="Create unit", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get unit of measure", tags=["Master Data"]),
    update=extend_schema(summary="Update unit", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update unit", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete unit", tags=["Master Data"]),
)
@method_decorator(vary_on_headers("Accept-Language"), name="list")
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name="list")
class UnitOfMeasureViewSet(_ActiveOnlyListMixin, viewsets.ModelViewSet):
    """CRUD for units of measure (read: public; write: admin)."""

    queryset = UnitOfMeasure.objects.all().order_by("sort_order", "code")
    serializer_class = UnitOfMeasureSerializer
    permission_classes = [IsPlatformAdminOrReadOnly]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(summary="List delivery basis", tags=["Master Data"]),
    create=extend_schema(summary="Create delivery basis", description="Admin only.", tags=["Master Data"]),
    retrieve=extend_schema(summary="Get delivery basis", tags=["Master Data"]),
    update=extend_schema(summary="Update delivery basis", description="Admin only.", tags=["Master Data"]),
    partial_update=extend_schema(summary="Partially update delivery basis", tags=["Master Data"]),
    destroy=extend_schema(summary="Delete delivery basis", tags=["Master Data"]),
)
@method_decorator(vary_on_headers("Accept-Language"), name="list")
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name="list")
class DeliveryBasisViewSet(_ActiveOnlyListMixin, viewsets.ModelViewSet):
    """CRUD for delivery basis terms (Incoterms). Read: public; write: admin."""

    queryset = DeliveryBasis.objects.all().order_by("sort_order", "code")
    serializer_class = DeliveryBasisSerializer
    permission_classes = [IsPlatformAdminOrReadOnly]
    pagination_class = None


@extend_schema(
    summary="Таможенные платежи по коду ТН ВЭД (витрина интегрированного тарифа ГТК)",
    description=(
        "Ставки сбора/пошлины/акциза/НДС и разрешительные документы по коду и стране "
        "происхождения. Данные НЕ хранятся у нас: запрос к tarif.customs.uz с суточным "
        "кэшем. 503 HS_DUTIES_UNAVAILABLE — источник недоступен, интерфейс показывает "
        "ссылку на калькулятор ГТК."
    ),
    tags=["Master Data"],
    parameters=[
        OpenApiParameter("origin", str, description="Код страны происхождения (ISO alpha-2, напр. CN)"),
    ],
    responses={200: OpenApiResponse(description="{payments, permits, fetched_at, source_url}")},
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def hs_code_duties(request, code: str):
    """Платежи по коду ТН ВЭД — тонкая обёртка над `customs_duties.get_duties` (Rule 8).

    Код проверяем ПО СВОЕМУ справочнику: гонять произвольные цифры в чужой сервис незачем,
    а «код есть в тарифе, но не в классификаторе» — сигнал, что справочник пора синхронизировать.
    """
    from .customs_duties import DutiesUnavailable, get_duties

    digits = "".join(char for char in (code or "") if char.isdigit())
    hs_code = HSCode.objects.filter(code=digits).first()
    if not hs_code:
        return Response({"detail": "HS_CODE_UNKNOWN"}, status=status.HTTP_404_NOT_FOUND)

    origin = (request.query_params.get("origin") or "").strip().upper()
    country = Country.objects.filter(code=origin).first() if origin else None
    if not country or not country.iso_numeric:
        # Страна происхождения определяет преференции — без неё ставка бессмысленна.
        # Пустой iso_numeric = запись завёл оператор вручную, тарифу её не скормить.
        return Response({"detail": "ORIGIN_COUNTRY_REQUIRED"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        duties = get_duties(hs_code.code, country.iso_numeric)
    except DutiesUnavailable:
        return Response({"detail": "HS_DUTIES_UNAVAILABLE"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({**duties, "hs_code": hs_code.code, "hs_name": hs_code.name, "origin": country.code})
