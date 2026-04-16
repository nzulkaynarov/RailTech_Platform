from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from drf_spectacular.utils import extend_schema, extend_schema_view
from .models import Country, Currency, UnitOfMeasure, DeliveryBasis
from .serializers import (
    CountrySerializer, CurrencySerializer,
    UnitOfMeasureSerializer, DeliveryBasisSerializer
)


@extend_schema_view(
    list=extend_schema(
        summary="List countries",
        description="Returns all active countries.",
        tags=['Master Data'],
    ),
    retrieve=extend_schema(summary="Get country", tags=['Master Data']),
)
class CountryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only lookup for countries."""
    queryset = Country.objects.filter(is_active=True)
    serializer_class = CountrySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


@extend_schema_view(
    list=extend_schema(
        summary="List currencies",
        description="Returns all active currencies (e.g. USD, UZS, EUR).",
        tags=['Master Data'],
    ),
    retrieve=extend_schema(summary="Get currency", tags=['Master Data']),
)
class CurrencyViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only lookup for currencies."""
    queryset = Currency.objects.filter(is_active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


@extend_schema_view(
    list=extend_schema(
        summary="List units of measure",
        description="Returns all active units of measure (e.g. PCS, KG, M).",
        tags=['Master Data'],
    ),
    retrieve=extend_schema(summary="Get unit of measure", tags=['Master Data']),
)
class UnitOfMeasureViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only lookup for units of measure."""
    queryset = UnitOfMeasure.objects.filter(is_active=True)
    serializer_class = UnitOfMeasureSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


@extend_schema_view(
    list=extend_schema(
        summary="List delivery basis",
        description="Returns all active delivery basis terms (Incoterms).",
        tags=['Master Data'],
    ),
    retrieve=extend_schema(summary="Get delivery basis", tags=['Master Data']),
)
class DeliveryBasisViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only lookup for delivery basis (Incoterms)."""
    queryset = DeliveryBasis.objects.filter(is_active=True)
    serializer_class = DeliveryBasisSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
