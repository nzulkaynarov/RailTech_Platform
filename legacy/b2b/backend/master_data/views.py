from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from drf_spectacular.utils import extend_schema, extend_schema_view
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from .models import Country, Currency, UnitOfMeasure, DeliveryBasis
from .serializers import (
    CountrySerializer, CurrencySerializer,
    UnitOfMeasureSerializer, DeliveryBasisSerializer
)

LOOKUP_CACHE_TTL = 60 * 10  # 10 min — master data changes rarely


@extend_schema_view(
    list=extend_schema(
        summary="List countries",
        description="Returns all active countries.",
        tags=['Master Data'],
    ),
    retrieve=extend_schema(summary="Get country", tags=['Master Data']),
)
@method_decorator(vary_on_headers('Accept-Language'), name='list')
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name='list')
class CountryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only lookup for countries."""
    queryset = Country.objects.filter(is_active=True)
    serializer_class = CountrySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(
        summary="List currencies",
        description="Returns all active currencies (e.g. USD, UZS, EUR).",
        tags=['Master Data'],
    ),
    retrieve=extend_schema(summary="Get currency", tags=['Master Data']),
)
@method_decorator(vary_on_headers('Accept-Language'), name='list')
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name='list')
class CurrencyViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only lookup for currencies."""
    queryset = Currency.objects.filter(is_active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(
        summary="List units of measure",
        description="Returns all active units of measure (e.g. PCS, KG, M).",
        tags=['Master Data'],
    ),
    retrieve=extend_schema(summary="Get unit of measure", tags=['Master Data']),
)
@method_decorator(vary_on_headers('Accept-Language'), name='list')
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name='list')
class UnitOfMeasureViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only lookup for units of measure."""
    queryset = UnitOfMeasure.objects.filter(is_active=True)
    serializer_class = UnitOfMeasureSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = None


@extend_schema_view(
    list=extend_schema(
        summary="List delivery basis",
        description="Returns all active delivery basis terms (Incoterms).",
        tags=['Master Data'],
    ),
    retrieve=extend_schema(summary="Get delivery basis", tags=['Master Data']),
)
@method_decorator(vary_on_headers('Accept-Language'), name='list')
@method_decorator(cache_page(LOOKUP_CACHE_TTL), name='list')
class DeliveryBasisViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only lookup for delivery basis (Incoterms)."""
    queryset = DeliveryBasis.objects.filter(is_active=True)
    serializer_class = DeliveryBasisSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = None
