"""Отклонение маржи сделки и факт закупки (M1-ERP-08) — тонкие вьюхи над `finance.services.margin_deviation`.

Чтение — только с `quote.view_cost_margin` (себестоимость и маржа); факт закупки — `finance.rates` или
`supply.manage` (гейт `required_permissions` + та же проверка в сервисе).
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from finance.serializers import MarginDeviationSerializer, PurchaseActualSerializer
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import RoleGatedViewMixin

PURCHASE_ACTUAL_PERMISSIONS = ("finance.rates", "supply.manage")
_STATUS_BY_CODE = {
    "ROLE_NOT_PERMITTED": status.HTTP_403_FORBIDDEN,
    "MARGIN_NO_REFERENCE_QUOTE": status.HTTP_409_CONFLICT,
}
_ERRORS = (
    "MARGIN_NO_REFERENCE_QUOTE / PURCHASE_CURRENCY_NOT_IN_QUOTE / PURCHASE_DATE_IN_FUTURE / "
    "PURCHASE_AMOUNT_INVALID / PURCHASE_NOTE_TOO_LONG / FX_RATE_INVALID / FX_RATE_MISSING"
)


def _deal(deal_id):
    from crm.models import Deal

    return get_object_or_404(Deal.objects.select_related("company"), pk=deal_id)


def _deviation_response(deal):
    from finance.services.margin_deviation import compute_margin_deviation

    return Response(MarginDeviationSerializer(compute_margin_deviation(deal)).data)


def _error(exc):
    code = str(exc)
    return Response({"detail": code}, status=_STATUS_BY_CODE.get(code, status.HTTP_400_BAD_REQUEST))


class DealMarginDeviationView(RoleGatedViewMixin, APIView):
    """GET — отклонение маржи сделки (опорное КП против факта закупки)."""

    permission_classes = [IsAuthenticated]
    required_permissions: dict = {}

    @extend_schema(
        summary="Deal margin deviation (actual purchase vs quote snapshot)",
        responses={200: MarginDeviationSerializer, 403: OpenApiResponse(description="ROLE_NOT_PERMITTED")},
        tags=["Finance"],
    )
    def get(self, request, deal_id: int):
        from accounts.services.permissions import can_view_quote_costs

        if not can_view_quote_costs(request.user):
            return Response({"detail": "ROLE_NOT_PERMITTED"}, status=status.HTTP_403_FORBIDDEN)
        return _deviation_response(_deal(deal_id))


class DealPurchaseActualsView(RoleGatedViewMixin, APIView):
    """POST — внести/обновить факт закупки по валюте (одна строка на валюту сделки)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"POST": PURCHASE_ACTUAL_PERMISSIONS}

    @extend_schema(
        summary="Record the actual purchase for one currency of the deal",
        request=PurchaseActualSerializer,
        responses={
            200: MarginDeviationSerializer,
            400: OpenApiResponse(description=_ERRORS),
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED"),
            409: OpenApiResponse(description="MARGIN_NO_REFERENCE_QUOTE"),
        },
        tags=["Finance"],
    )
    def post(self, request, deal_id: int):
        from finance.services.margin_deviation import MarginDeviationError, PurchaseActualInput, record_purchase_actual

        deal = _deal(deal_id)
        payload = PurchaseActualSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            record_purchase_actual(deal, actor=request.user, data=PurchaseActualInput(**payload.validated_data))
        except MarginDeviationError as exc:
            return _error(exc)
        return _deviation_response(deal)


class DealPurchaseActualDetailView(RoleGatedViewMixin, APIView):
    """DELETE — убрать факт закупки по валюте (маржа по этой валюте снова как в КП)."""

    permission_classes = [IsAuthenticated]
    required_permissions = {"DELETE": PURCHASE_ACTUAL_PERMISSIONS}

    @extend_schema(
        summary="Remove the actual purchase for one currency of the deal",
        request=None,
        responses={200: MarginDeviationSerializer, 403: OpenApiResponse(description="ROLE_NOT_PERMITTED")},
        tags=["Finance"],
    )
    def delete(self, request, deal_id: int, currency: str):
        from finance.services.margin_deviation import MarginDeviationError, remove_purchase_actual

        deal = _deal(deal_id)
        try:
            remove_purchase_actual(deal, actor=request.user, currency=currency)
        except MarginDeviationError as exc:
            return _error(exc)
        return _deviation_response(deal)
