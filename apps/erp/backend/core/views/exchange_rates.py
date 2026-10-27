"""Курс валюты к UZS: текущий, журнал и ручной ввод (W13C-F6, экран «Компания» → «Платформа»).

Автозагрузку курса ЦБ РУз ведёт задача Beat (`master_data.tasks.refresh_exchange_rates`). Если она не сработала,
оператор вводит курс на дату вручную: право `settings.edit` (его даёт раздел Платформы «Компания») или администратор.
Строка справочника `core.ExchangeRate` с источником `MANUAL` автозагрузка не перетирает; кто, когда и что ввёл — в
журнале ERP (`crm.ActivityLog`, `event_code = admin.exchange_rate.*`). Текущий курс читает любой вошедший (его уже
отдаёт `system-settings`); журнал с именами и почтой коллег — только `settings.edit` или администратор (W15-H8).
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from finance.services.fx import (
    AUTO_SKIPPED_EVENT,
    TRACKED_CURRENCIES,
    fx_journal,
    max_rate_age_days,
    normalize_code,
    rate_to_str,
    resolve_rate,
    set_manual_rate,
)
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import RoleGatedViewMixin

JOURNAL_DEFAULT_LIMIT = 20
JOURNAL_MAX_LIMIT = 100
_CURRENCY_PARAM = OpenApiParameter("currency", str, description="Код валюты (USD, EUR, RUB); по умолчанию USD.")


class _RateSerializer(serializers.Serializer):
    currency = serializers.CharField()
    rate_to_uzs = serializers.CharField(help_text="Сумов за 1 единицу валюты, без хвостовых нулей.")
    rate_date = serializers.DateField()
    source = serializers.CharField(help_text="CBU (автозагрузка ЦБ РУз) или MANUAL (вручную).")


class CurrentRateSerializer(serializers.Serializer):
    currency = serializers.CharField()
    current = _RateSerializer(
        allow_null=True, help_text="Курс на сегодня по правилу «не старше лимита»; null — курса нет."
    )
    max_age_days = serializers.IntegerField()


class ManualRateInSerializer(serializers.Serializer):
    """Тело ручного ввода. Проверку значений делает сервис (коды `FX_*`), здесь — только форма."""

    currency = serializers.CharField(required=False, default="USD")
    rate_date = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Дата курса, YYYY-MM-DD; не позже сегодня и не старше 366 дней.",
    )
    rate_to_uzs = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Курс > 0, не больше 6 знаков после запятой."
    )


class JournalEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["manual", "auto_skipped"])
    currency = serializers.CharField()
    rate_date = serializers.DateField()
    rate_to_uzs = serializers.CharField()
    previous_rate_to_uzs = serializers.CharField(allow_null=True)
    previous_source = serializers.CharField(allow_null=True)
    entered_by_id = serializers.IntegerField(allow_null=True)
    entered_by_email = serializers.CharField(allow_blank=True)
    entered_by_name = serializers.CharField(allow_blank=True)
    entered_at = serializers.DateTimeField()


def _currency(request) -> str:
    return normalize_code(request.query_params.get("currency") or "USD")


def _bad_currency():
    return Response({"detail": "FX_CURRENCY_UNSUPPORTED"}, status=status.HTTP_400_BAD_REQUEST)


def _entry(log) -> dict:
    before, after, params = log.before_data or {}, log.after_data or {}, log.event_params or {}
    user = log.user
    return {
        "id": log.pk,
        "kind": "auto_skipped" if log.event_code == AUTO_SKIPPED_EVENT else "manual",
        "currency": params.get("currency", ""),
        "rate_date": params.get("rate_date"),
        "rate_to_uzs": after.get("rate_to_uzs", ""),
        "previous_rate_to_uzs": before.get("rate_to_uzs"),
        "previous_source": before.get("source"),
        "entered_by_id": user.pk if user else None,
        "entered_by_email": user.email if user else "",
        "entered_by_name": (user.get_full_name() if user else "") or "",
        "entered_at": log.timestamp,
    }


class CanReadRateJournal(permissions.BasePermission):
    """Журнал курсов видит тот, кто может править настройки: `settings.edit` или администратор."""

    message = "SETTINGS_EDIT_REQUIRED"

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        from accounts.services.permissions import is_seller, staff_has_permission

        return is_seller(user) and staff_has_permission(user, "settings.edit")


class CurrentRateView(APIView):
    """GET /api/v1/exchange-rates/current/ — курс на сегодня, его дата и источник."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Current exchange rate to UZS",
        description="Rate for today by the freshness rule (latest row not older than the company limit); `current` null — no rate.",
        parameters=[_CURRENCY_PARAM],
        responses={200: CurrentRateSerializer, 400: OpenApiResponse(description="FX_CURRENCY_UNSUPPORTED")},
        tags=["Finance"],
    )
    def get(self, request):
        code = _currency(request)
        if code not in TRACKED_CURRENCIES:
            return _bad_currency()
        resolved = resolve_rate(code)
        current = (
            {
                "currency": code,
                "rate_to_uzs": rate_to_str(resolved.rate),
                "rate_date": resolved.rate_date,
                "source": resolved.source,
            }
            if resolved
            else None
        )
        return Response(
            CurrentRateSerializer({"currency": code, "current": current, "max_age_days": max_rate_age_days()}).data
        )


class ExchangeRateJournalView(APIView):
    """GET /api/v1/exchange-rates/journal/ — последние ручные вводы курса и пропуски автозагрузки."""

    permission_classes = [permissions.IsAuthenticated, CanReadRateJournal]

    @extend_schema(
        summary="Exchange rate manual-entry journal",
        description="Needs `settings.edit` or administrator (the journal carries colleagues' names and emails). Newest first. `kind=manual` — entered by an operator; `kind=auto_skipped` — the CBU rate for the same date was not applied because a manual rate is kept.",
        parameters=[
            _CURRENCY_PARAM,
            OpenApiParameter("limit", int, description=f"1..{JOURNAL_MAX_LIMIT}, default {JOURNAL_DEFAULT_LIMIT}."),
        ],
        responses={200: JournalEntrySerializer(many=True), 400: OpenApiResponse(description="FX_CURRENCY_UNSUPPORTED")},
        tags=["Finance"],
    )
    def get(self, request):
        code = _currency(request)
        if code not in TRACKED_CURRENCIES:
            return _bad_currency()
        try:
            limit = int(request.query_params.get("limit") or JOURNAL_DEFAULT_LIMIT)
        except ValueError:
            limit = JOURNAL_DEFAULT_LIMIT
        limit = max(1, min(limit, JOURNAL_MAX_LIMIT))
        return Response(JournalEntrySerializer([_entry(log) for log in fx_journal(code, limit)], many=True).data)


class ManualRateView(RoleGatedViewMixin, APIView):
    """POST /api/v1/exchange-rates/manual/ — ввести курс на дату вручную."""

    required_permissions = {"POST": "settings.edit"}
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Enter an exchange rate manually",
        description=(
            "Needs `settings.edit` or administrator. Replaces the row for (currency, date) — a CBU rate or an earlier manual "
            "one; the previous value stays in the journal. The CBU auto-load does not overwrite a manual rate. Errors are "
            "`{detail: CODE}`: FX_CURRENCY_UNSUPPORTED, FX_RATE_INVALID, FX_RATE_DATE_INVALID, FX_RATE_DATE_IN_FUTURE, "
            "FX_RATE_DATE_TOO_OLD."
        ),
        request=ManualRateInSerializer,
        responses={201: _RateSerializer, 400: OpenApiResponse(description="FX_* validation code")},
        tags=["Finance"],
    )
    def post(self, request):
        body = ManualRateInSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        row, error = set_manual_rate(
            currency_code=data["currency"],
            rate_date=data["rate_date"],
            rate=data["rate_to_uzs"],
            actor=request.user,
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            _RateSerializer(
                {
                    "currency": row.currency.code,
                    "rate_to_uzs": rate_to_str(row.rate_to_uzs),
                    "rate_date": row.rate_date,
                    "source": row.source,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )
