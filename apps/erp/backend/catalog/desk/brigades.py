"""Бригады и исполнители услуг (D2-3): список, создание, правка. Ставку видит и меняет только держатель зоны услуг или
`quote.view_cost_margin` (`catalog.desk.access.can_view_crew_rates`); остальным ERP отдаёт `rate = null`."""

from decimal import Decimal, InvalidOperation

from django.db.models import Q

from catalog.desk.access import can_view_crew_rates
from catalog.desk.items import ItemError
from catalog.models import Brigade
from core.models import Currency


def list_queryset(params):
    queryset = Brigade.objects.select_related("currency")
    text = (params.get("q") or "").strip()
    if text:
        queryset = queryset.filter(Q(name__icontains=text) | Q(specialization__icontains=text))
    if params.get("kind") in Brigade.Kind.values:
        queryset = queryset.filter(kind=params["kind"])
    if str(params.get("include_inactive", "")).lower() not in ("1", "true"):
        queryset = queryset.filter(is_active=True)
    return queryset.order_by("name", "id")


def brigade_row(brigade, user) -> dict:
    visible = can_view_crew_rates(user)
    rate = None
    if visible and brigade.rate is not None:
        rate = {
            "amount": f"{brigade.rate:.2f}",
            "currency": brigade.currency.code if brigade.currency_id else None,
            "unit": brigade.rate_unit,
        }
    return {
        "id": brigade.pk,
        "name": brigade.name,
        "kind": brigade.kind,
        "specialization": brigade.specialization,
        "headcount": brigade.headcount,
        "rate": rate,
        "rate_visible": visible,
        "note": brigade.note,
        "is_active": brigade.is_active,
    }


def _apply_rate(brigade, data: dict, user) -> None:
    touched = {"rate", "rate_unit"} & data.keys()
    if not touched:
        return
    if not can_view_crew_rates(user):
        raise ItemError("CREW_RATES_REQUIRED", "rate")
    if "rate_unit" in data:
        if data["rate_unit"] not in Brigade.RateUnit.values:
            raise ItemError("RATE_UNIT_INVALID", "rate_unit")
        brigade.rate_unit = data["rate_unit"]
    if "rate" not in data:
        return
    rate = data["rate"]
    if rate is None:
        brigade.rate, brigade.currency = None, None
        return
    if not isinstance(rate, dict):
        raise ItemError("CREW_RATE_INVALID", "rate")
    try:
        amount = Decimal(str(rate.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ItemError("CREW_RATE_INVALID", "rate") from None
    if amount < 0 or amount >= Decimal("1e12"):
        raise ItemError("CREW_RATE_INVALID", "rate")
    currency = Currency.objects.filter(code=rate.get("currency"), is_active=True).first()
    if currency is None:
        raise ItemError("CREW_CURRENCY_INVALID", "rate")
    brigade.rate, brigade.currency = amount, currency


def save_brigade(brigade, data: dict, user) -> Brigade:
    if "name" in data or brigade.pk is None:
        name = (data.get("name") or "").strip()
        if not name:
            raise ItemError("BRIGADE_NAME_REQUIRED", "name")
        brigade.name = name[:255]
    if "kind" in data:
        if data["kind"] not in Brigade.Kind.values:
            raise ItemError("BRIGADE_KIND_INVALID", "kind")
        brigade.kind = data["kind"]
    if "specialization" in data:
        brigade.specialization = (data["specialization"] or "")[:255]
    if "headcount" in data:
        value = data["headcount"]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 500:
            raise ItemError("BRIGADE_HEADCOUNT_INVALID", "headcount")
        brigade.headcount = value
    if "note" in data:
        brigade.note = (data["note"] or "")[:500]
    if "is_active" in data:
        brigade.is_active = bool(data["is_active"])
    _apply_rate(brigade, data, user)
    brigade.save()
    return brigade
