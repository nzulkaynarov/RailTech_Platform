from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets

from core.permissions import IsPlatformAdminOrReadOnly

from .models import Country, Currency, DeliveryBasis, UnitOfMeasure
from .serializers import CountrySerializer, CurrencySerializer, DeliveryBasisSerializer, UnitOfMeasureSerializer

LOOKUP_CACHE_TTL = 60 * 10  # 10 min — master data changes rarely


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
class CountryViewSet(viewsets.ModelViewSet):
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
class CurrencyViewSet(viewsets.ModelViewSet):
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
class UnitOfMeasureViewSet(viewsets.ModelViewSet):
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
class DeliveryBasisViewSet(viewsets.ModelViewSet):
    """CRUD for delivery basis terms (Incoterms). Read: public; write: admin."""

    queryset = DeliveryBasis.objects.all().order_by("sort_order", "code")
    serializer_class = DeliveryBasisSerializer
    permission_classes = [IsPlatformAdminOrReadOnly]
    pagination_class = None
