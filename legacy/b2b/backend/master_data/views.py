from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from .models import Country, Currency, UnitOfMeasure, DeliveryBasis
from .serializers import (
    CountrySerializer, CurrencySerializer,
    UnitOfMeasureSerializer, DeliveryBasisSerializer
)


class CountryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Country.objects.filter(is_active=True)
    serializer_class = CountrySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class CurrencyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Currency.objects.filter(is_active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class UnitOfMeasureViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UnitOfMeasure.objects.filter(is_active=True)
    serializer_class = UnitOfMeasureSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class DeliveryBasisViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DeliveryBasis.objects.filter(is_active=True)
    serializer_class = DeliveryBasisSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
