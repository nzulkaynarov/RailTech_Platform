"""Отклонение маржи при фактической закупке (M1-ERP-08; сама закупка — M4).

КП фиксирует курс на свою дату и цену клиенту; фактическая закупка идёт по другому курсу и/или
другой цене. Цена клиенту не пересчитывается (BUSINESS «Курс валюты»), меняется маржа сделки — её и
показывает карточка сделки.

Формула (Decimal, деньги — до копейки 0.5 вверх, проценты — до 0.01 0.5 вверх):

* Опорное КП — принятое клиентом (APPROVED) последней версии, иначе последнее отправленное.
* Выручка `P` = сумма позиций КП без НДС (`subtotal_excl_vat`, без статей расходов) — та же база,
  что у валовой маржи в экономике КП.
* По каждой валюте себестоимости `C` строк КП:
  - в КП: `Q_C` = Σ (цена поставщика + пошлина) × кол-во в валюте; себестоимость в сумах
    `QS_C` = Σ landed_cost × кол-во (ровно то, что посчитал движок КП по курсу снимка);
  - по факту: сумма `A_C` (не задана — как в КП, `Q_C`) по курсу `r_C`: `AS_C` = округл(`A_C` × `r_C`);
    факта по валюте нет — `AS_C` = `QS_C`.
* Валовая прибыль: в КП `P − ΣQS`, по факту `P − ΣAS`; маржа — прибыль / `P` × 100 (`P = 0` → 0).
* Отклонение: сумма = прибыль по факту − прибыль в КП (= −Σ(AS − QS)); в п. п. = маржа по факту −
  маржа в КП; в % к прибыли КП = отклонение / прибыль КП × 100 (прибыль КП 0 → нет значения).
"""

import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone
from finance.services.fx import (
    BASE_CURRENCY,
    MONEY_QUANT,
    convert_to_base,
    normalize_code,
    parse_positive_rate,
    rate_to_str,
    resolve_rate,
)

PERCENT_QUANT = Decimal("0.01")
HUNDRED = Decimal("100")
NOTE_MAX_LEN = 500


class MarginDeviationError(ValueError):
    """Ошибка факта закупки; `str(exc)` — код API."""


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _percent(value: Decimal) -> Decimal:
    return Decimal(value).quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)


def actual_cost_in_base(quoted_amount, quoted_cost_base, actual_amount=None, actual_rate=None) -> Decimal:
    """Фактическая себестоимость валюты в сумах: нет факта — как в КП; сумма не задана — как в КП."""
    if actual_rate is None:
        return _money(quoted_cost_base)
    amount = quoted_amount if actual_amount is None else actual_amount
    return convert_to_base(amount, actual_rate)


def margin_summary(revenue, quoted_cost, actual_cost) -> dict:
    """Маржа в КП и по факту и их отклонение — чистая функция (параметризованный тест расчёта)."""
    revenue, quoted_cost, actual_cost = Decimal(revenue), Decimal(quoted_cost), Decimal(actual_cost)
    quoted_profit = revenue - quoted_cost
    actual_profit = revenue - actual_cost
    quoted_pct = quoted_profit / revenue * HUNDRED if revenue > 0 else Decimal("0")
    actual_pct = actual_profit / revenue * HUNDRED if revenue > 0 else Decimal("0")
    deviation = actual_profit - quoted_profit
    relative = _percent(deviation / quoted_profit * HUNDRED) if quoted_profit != 0 else None
    return {
        "revenue": _money(revenue),
        "quoted_cost": _money(quoted_cost),
        "quoted_profit": _money(quoted_profit),
        "quoted_margin_percent": _percent(quoted_pct),
        "actual_cost": _money(actual_cost),
        "actual_profit": _money(actual_profit),
        "actual_margin_percent": _percent(actual_pct),
        "deviation_amount": _money(deviation),
        "deviation_percent_points": _percent(actual_pct - quoted_pct),
        "deviation_profit_percent": relative,
    }


@dataclass
class _CurrencyLine:
    currency: str
    quoted_amount: Decimal = Decimal("0")
    quoted_cost: Decimal = Decimal("0")
    lines: int = 0
    actual: Optional[object] = field(default=None)


def reference_quote(deal):
    """Опорное КП сделки: принятое клиентом (последняя версия), иначе последнее отправленное; нет — None."""
    from crm.constants import QuoteStatusCode

    sent = list(deal.quotes.filter(frozen_at__isnull=False).select_related("status").order_by("-version"))
    accepted = [q for q in sent if q.status_id and q.status.code == QuoteStatusCode.APPROVED]
    return (accepted or sent or [None])[0]


def _currency_lines(quote) -> dict:
    lines: dict = {}
    for item in quote.items.billable().select_related("frozen_currency"):
        code = normalize_code(item.frozen_currency.code if item.frozen_currency_id else None)
        row = lines.setdefault(code, _CurrencyLine(code))
        row.quoted_amount += (item.frozen_base_price + item.customs_duty) * item.quantity
        row.quoted_cost += item.landed_cost * item.quantity
        row.lines += 1
    return lines


def _quoted_rate(quote, code):
    from sales.services.quote_fx import quote_fx_rates

    if code == BASE_CURRENCY:
        return "1", None
    for row in quote_fx_rates(quote, [code]):
        if row["currency"] == code:
            return row["rate"], row["rate_date"]
    return None, None


def _row_payload(quote, line: _CurrencyLine) -> dict:
    actual = line.actual
    actual_rate = Decimal(actual.rate_to_uzs) if actual else None
    actual_amount = actual.amount if actual else None
    actual_cost = actual_cost_in_base(line.quoted_amount, line.quoted_cost, actual_amount, actual_rate)
    quoted_rate, quoted_rate_date = _quoted_rate(quote, line.currency)
    suggested = resolve_rate(line.currency)
    entered_by = getattr(actual, "entered_by", None)
    return {
        "currency": line.currency,
        "lines": line.lines,
        "quoted_amount": _money(line.quoted_amount),
        "quoted_rate": quoted_rate,
        "quoted_rate_date": quoted_rate_date,
        "quoted_cost": _money(line.quoted_cost),
        "has_actual": actual is not None,
        "actual_amount": _money(actual_amount) if actual_amount is not None else None,
        "actual_rate": rate_to_str(actual_rate) if actual_rate is not None else None,
        "actual_cost": actual_cost,
        "cost_deviation": _money(actual_cost - line.quoted_cost),
        "purchased_on": actual.purchased_on.isoformat() if actual else None,
        "note": actual.note if actual else "",
        "entered_by_name": (entered_by.get_full_name() or entered_by.email) if entered_by else "",
        "suggested_rate": rate_to_str(suggested.rate) if suggested else None,
        "suggested_rate_date": suggested.rate_date.isoformat() if suggested and suggested.rate_date else None,
    }


def compute_margin_deviation(deal) -> dict:
    """Отклонение маржи сделки для карточки сделки (только с `quote.view_cost_margin` — гейт во вьюхе)."""
    quote = reference_quote(deal)
    if quote is None:
        return {"deal": deal.pk, "currency": BASE_CURRENCY, "reference_quote": None, "rows": [], "has_actuals": False}
    lines = _currency_lines(quote)
    for actual in deal.purchase_actuals.select_related("currency", "entered_by"):
        code = normalize_code(actual.currency.code)
        if code in lines:
            lines[code].actual = actual
    rows = [_row_payload(quote, lines[code]) for code in sorted(lines)]
    quoted_cost = sum((row["quoted_cost"] for row in rows), Decimal("0"))
    actual_cost = sum((row["actual_cost"] for row in rows), Decimal("0"))
    summary = margin_summary(quote.subtotal_excl_vat or Decimal("0"), quoted_cost, actual_cost)
    return {
        "deal": deal.pk,
        "currency": BASE_CURRENCY,
        "reference_quote": {
            "id": quote.pk,
            "version": quote.version,
            "number": quote.number or "",
            "status_code": quote.status.code if quote.status_id else "",
            "frozen_at": quote.frozen_at.isoformat() if quote.frozen_at else None,
            "fx_fixed_at": quote.fx_fixed_at.isoformat() if quote.fx_fixed_at else None,
        },
        "rows": rows,
        "has_actuals": any(row["has_actual"] for row in rows),
        **summary,
    }


@dataclass(frozen=True)
class PurchaseActualInput:
    currency: str
    amount: object = None
    rate: object = None
    purchased_on: Optional[datetime.date] = None
    note: str = ""


def _validated_input(quote, data: PurchaseActualInput):
    code = normalize_code(data.currency)
    if code not in _currency_lines(quote):
        raise MarginDeviationError("PURCHASE_CURRENCY_NOT_IN_QUOTE")
    purchased_on = data.purchased_on or timezone.localdate()
    if purchased_on > timezone.localdate():
        raise MarginDeviationError("PURCHASE_DATE_IN_FUTURE")
    amount = _validated_amount(data.amount)
    note = (data.note or "").strip()
    if len(note) > NOTE_MAX_LEN:
        raise MarginDeviationError("PURCHASE_NOTE_TOO_LONG")
    return code, amount, _purchase_rate(code, data.rate, purchased_on), purchased_on, note


def _validated_amount(value) -> Optional[Decimal]:
    """Фактическая сумма в валюте: пусто — как в КП; иначе число ≥ 0 с копейками."""
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except ArithmeticError:
        raise MarginDeviationError("PURCHASE_AMOUNT_INVALID")
    if not amount.is_finite() or amount < 0 or amount != _money(amount) or amount >= Decimal("1e14"):
        raise MarginDeviationError("PURCHASE_AMOUNT_INVALID")
    return amount


def _purchase_rate(code, rate, purchased_on) -> Decimal:
    if code == BASE_CURRENCY:
        return Decimal("1")
    if rate not in (None, ""):
        parsed = parse_positive_rate(rate)
        if parsed is None or parsed != parsed.quantize(Decimal("0.000001")):
            raise MarginDeviationError("FX_RATE_INVALID")
        return parsed
    resolved = resolve_rate(code, purchased_on)
    if resolved is None:
        raise MarginDeviationError("FX_RATE_MISSING")
    return resolved.rate


def _assert_can_record(actor) -> None:
    from accounts.services.permissions import can_record_purchase_actuals

    if not can_record_purchase_actuals(actor):
        raise MarginDeviationError("ROLE_NOT_PERMITTED")


def record_purchase_actual(deal, *, actor, data: PurchaseActualInput):
    """Внести/обновить факт закупки по валюте сделки (одна строка на валюту), в журнал сделки."""
    from finance.models import DealPurchaseActual

    from core.models import Currency

    _assert_can_record(actor)
    quote = reference_quote(deal)
    if quote is None:
        raise MarginDeviationError("MARGIN_NO_REFERENCE_QUOTE")
    code, amount, rate, purchased_on, note = _validated_input(quote, data)
    currency = Currency.objects.filter(code=code).first()
    if currency is None:
        raise MarginDeviationError("FX_CURRENCY_UNKNOWN")
    with transaction.atomic():
        previous = DealPurchaseActual.objects.filter(deal=deal, currency=currency).first()
        before = _snapshot(previous)
        actual, _created = DealPurchaseActual.objects.update_or_create(
            deal=deal,
            currency=currency,
            defaults={
                "amount": amount,
                "rate_to_uzs": rate,
                "purchased_on": purchased_on,
                "note": note,
                "entered_by": actor,
            },
        )
        _log(deal, actor, "deal.purchase_actual_set", code, before, _snapshot(actual), note)
    return actual


def remove_purchase_actual(deal, *, actor, currency: str) -> None:
    """Удалить факт закупки по валюте (маржа снова как в КП), в журнал сделки; нет факта — no-op."""
    from finance.models import DealPurchaseActual

    _assert_can_record(actor)
    code = normalize_code(currency)
    with transaction.atomic():
        actual = DealPurchaseActual.objects.filter(deal=deal, currency__code=code).first()
        if actual is None:
            return
        before = _snapshot(actual)
        actual.delete()
        _log(deal, actor, "deal.purchase_actual_removed", code, before, None, "")


def _snapshot(actual) -> Optional[dict]:
    if actual is None:
        return None
    return {
        "amount": str(actual.amount) if actual.amount is not None else None,
        "rate": rate_to_str(Decimal(actual.rate_to_uzs)),
        "purchased_on": actual.purchased_on.isoformat(),
    }


def _log(deal, actor, event_code, code, before, after, note) -> None:
    from core.audit import log_admin_action

    removed = after is None
    rate = (after or {}).get("rate") or ""
    amount = (after or {}).get("amount") or ""
    detail = f"{code}: удалено" if removed else f"{code}: сумма {amount or 'как в КП'}, курс {rate}"
    log_admin_action(
        entity_type="deal",
        entity_id=deal.pk,
        action="Факт закупки удалён" if removed else "Факт закупки внесён",
        detail=detail,
        actor=actor,
        reason=note,
        before=before,
        after=after,
        deal_id=deal.pk,
        company_id=deal.company_id,
        event_code=event_code,
        event_params={"currency": code, "rate": rate, "amount": amount},
    )
