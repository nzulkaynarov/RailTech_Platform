"""Справочники «только в Django admin» → API для Платформы (D2-3, B-035, Q-W13A3-1 п. 2): коды ТН ВЭД, курсы валют.

Производители — `catalog.views.lookups.ManufacturerViewSet` (запись по `catalog.manage`). Курс на дату вводит
`exchange-rates/manual/` (`settings.edit`), здесь — список строк справочника для просмотра. Поля `maintenance_mode` и
`is_two_factor_required` не выводятся (переключатели, способные закрыть вход всем).
"""

from django.db.models import Q
from django.utils import timezone
from finance.services.fx import rate_to_str

from catalog.desk.items import ItemError
from catalog.models import HSCode
from core.models import ExchangeRate

HS_LEVELS = (2, 4, 6, 8, 10)


def hs_queryset(params):
    queryset = HSCode.objects.all()
    text = (params.get("q") or "").strip()
    if text:
        queryset = queryset.filter(Q(code__startswith=text) | Q(name__icontains=text))
    level = params.get("level")
    if str(level).isdigit():
        queryset = queryset.filter(level=int(level))
    if str(params.get("active", "")).lower() in ("1", "true"):
        today = timezone.localdate()
        queryset = queryset.filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today)).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=today)
        )
    return queryset.order_by("code")


def hs_row(code) -> dict:
    return {
        "id": code.pk,
        "code": code.code,
        "name": code.name,
        "unit_name": code.unit_name,
        "extra_unit_name": code.extra_unit_name,
        "level": code.level,
        "valid_from": code.valid_from,
        "valid_until": code.valid_until,
        "is_active": code.is_active,
        "source": code.source,
    }


def _dates(code, data: dict) -> None:
    for field in ("valid_from", "valid_until"):
        if field in data:
            setattr(code, field, data[field])
    if code.valid_from and code.valid_until and code.valid_until < code.valid_from:
        raise ItemError("HS_VALIDITY_RANGE_INVALID", "valid_until")


def _text(code, data: dict) -> None:
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise ItemError("HS_NAME_REQUIRED", "name")
        code.name = name
    for field in ("unit_name", "extra_unit_name"):
        if field in data:
            setattr(code, field, (data[field] or "").strip()[:64])


def create_hs(data: dict) -> HSCode:
    value = (data.get("code") or "").strip()
    if not value.isdigit() or len(value) not in HS_LEVELS:
        raise ItemError("HS_CODE_INVALID", "code")
    if HSCode.objects.filter(code=value).exists():
        raise ItemError("HS_CODE_EXISTS", "code")
    code = HSCode(code=value, level=len(value), source="manual")
    _text(code, {"name": data.get("name"), **{k: data[k] for k in ("unit_name", "extra_unit_name") if k in data}})
    _dates(code, data)
    prefixes = [value[:n] for n in HS_LEVELS if n < len(value)]
    code.parent = HSCode.objects.filter(code__in=prefixes).order_by("-level").first()
    code.save()
    return code


def update_hs(code: HSCode, data: dict) -> HSCode:
    _text(code, data)
    _dates(code, data)
    code.save()
    return code


def rates_queryset(params):
    queryset = ExchangeRate.objects.select_related("currency")
    currency = (params.get("currency") or "").strip().upper()
    if currency:
        queryset = queryset.filter(currency__code=currency)
    return queryset.order_by("-rate_date", "currency__code")


def rate_row(rate: ExchangeRate) -> dict:
    return {
        "id": rate.pk,
        "currency": rate.currency.code,
        "rate_to_uzs": rate_to_str(rate.rate_to_uzs),
        "rate_date": rate.rate_date,
        "source": rate.source,
    }
