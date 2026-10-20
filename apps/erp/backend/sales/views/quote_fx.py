"""Договорной курс КП (M1-ERP-08) — действие `POST crm/quotes/{id}/fx-override/` для `QuoteViewSet`.

Тонкая обёртка: гейт права (`finance.rates` в `required_permissions` вьюхи) → If-Match (оптимистичная
блокировка КП, как у PATCH) → сервис `sales.services.quote_fx.set_quote_rate_override` → КП целиком.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

# Коды сервиса → HTTP: конфликт состояния — 409, отказ по роли — 403, остальное — 400.
_STATUS_BY_CODE = {
    "ROLE_NOT_PERMITTED": status.HTTP_403_FORBIDDEN,
    "QUOTE_FROZEN": status.HTTP_409_CONFLICT,
    "QUOTE_NOT_DRAFT": status.HTTP_409_CONFLICT,
}


class QuoteFxOverrideSerializer(serializers.Serializer):
    currency = serializers.CharField(max_length=8, help_text="Код валюты себестоимости (не UZS).")
    rate = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=32,
        help_text="UZS за 1 единицу валюты (> 0, до 6 знаков после запятой); null или пусто — снять договорной курс.",
    )
    reason = serializers.CharField(max_length=500, allow_blank=True, help_text="Причина (обязательна, в журнал).")


class QuoteFxMixin:
    """Подмешивается в `QuoteViewSet`; объявление права — `required_permissions["fx_override"]`."""

    @extend_schema(
        summary="Set or clear the quote's negotiated FX rate",
        description=(
            "Договорной курс КП по валюте себестоимости (M1-ERP-08): побеждает курс ЦБ в снимке, "
            "КП пересчитывается. Только право `finance.rates`, причина обязательна, запись в журнал КП. "
            "Только в черновике КП: отправленное клиенту — 409 QUOTE_FROZEN, на согласовании и позже — 409 "
            "QUOTE_NOT_DRAFT (верните КП в черновик). `If-Match` с ETag КП — "
            "412 PRECONDITION_FAILED_STALE_WRITE, если КП изменилось после чтения."
        ),
        request=QuoteFxOverrideSerializer,
        responses={
            200: OpenApiResponse(description="КП после пересчёта (QuoteSerializer)"),
            400: OpenApiResponse(
                description="FX_CURRENCY_REQUIRED / FX_BASE_CURRENCY / FX_CURRENCY_UNKNOWN / FX_RATE_INVALID / "
                "FX_RATE_MUST_BE_POSITIVE / FX_OVERRIDE_REASON_REQUIRED / FX_OVERRIDE_REASON_TOO_LONG"
            ),
            403: OpenApiResponse(description="ROLE_NOT_PERMITTED"),
            409: OpenApiResponse(description="QUOTE_FROZEN / QUOTE_NOT_DRAFT"),
            412: OpenApiResponse(description="PRECONDITION_FAILED_STALE_WRITE"),
        },
        tags=["CRM"],
    )
    @action(detail=True, methods=["post"], url_path="fx-override")
    def fx_override(self, request, pk=None):
        from sales.services.quote_fx import QuoteFxError, set_quote_rate_override

        from crm.serializers import QuoteSerializer

        quote = self.get_object()
        if_match = request.headers.get("If-Match")
        if if_match and if_match != self._etag_for(quote):
            return Response({"detail": "PRECONDITION_FAILED_STALE_WRITE"}, status=status.HTTP_412_PRECONDITION_FAILED)
        payload = QuoteFxOverrideSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            quote = set_quote_rate_override(
                quote.pk,
                actor=request.user,
                currency=data["currency"],
                rate=data.get("rate"),
                reason=data.get("reason", ""),
            )
        except QuoteFxError as exc:
            code = str(exc)
            return Response({"detail": code}, status=_STATUS_BY_CODE.get(code, status.HTTP_400_BAD_REQUEST))
        response = Response(QuoteSerializer(quote, context=self.get_serializer_context()).data)
        response["ETag"] = self._etag_for(quote)
        return response
