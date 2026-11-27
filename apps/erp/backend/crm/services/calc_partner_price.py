"""РАСЧ-1: цена партнёра в строке расчёта — выбор лучшей действующей цены, перевод в валюту строки, источник.

Правило (решение владельца, стенд 2026-11-26, находка 7): закупка строки берёт **самую низкую действующую цену партнёра**,
сравнение — по курсу (в сумах), цена пишется в валюте строки (валюта себестоимости КП) после перевода по настроенному
курсу. Истёкшая цена молча не берётся никогда — строка остаётся без закупки, экран предлагает «Запросить цену». Цена без
курса (нет валюты в справочнике курсов на дату) в выбор не попадает: сравнить её честно нельзя.

Деньги — `Decimal`, округление до 0,01 вверх от половины (`ROUND_HALF_UP`), как в расчёте. Свежесть — `catalog/offer_freshness.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from django.utils import timezone

from core.currency import BASE_CURRENCY

_CENT = Decimal("0.01")
#: Сколько вариантов показывает короткий список «выбрать другой»; лучший — первый.
MAX_OPTIONS = 5

OK = "ok"
EXPIRING = "expiring"
STALE = "stale"


@dataclass(frozen=True)
class Option:
    """Действующая цена партнёра, приведённая к валюте строки."""

    offer: Any
    price: Decimal  # за единицу в валюте `currency`
    currency: str
    base: Decimal  # то же в сумах — ключ сравнения
    freshness: str
    price_date: date


def _code(offer) -> str:
    return (offer.currency.code if offer.currency_id else BASE_CURRENCY).upper()


def _rates(codes: Iterable[str], on_date: date) -> dict[str, Optional[Decimal]]:
    """Курс валюты к сумам на дату; нет курса — None. Лимит возраста курса читается один раз."""
    from finance.services.fx import max_rate_age_days, resolve_rate

    max_age = max_rate_age_days()
    found: dict[str, Optional[Decimal]] = {}
    for code in set(codes):
        resolved = resolve_rate(code, on_date, max_age_days=max_age)
        found[code] = Decimal(str(resolved.rate)) if resolved is not None else None
    return found


def _label(offer, *, today: date, now, confirm_days: int, expiring_days: int) -> str:
    from catalog import offer_freshness as fresh

    state = fresh.freshness(offer, today=today, now=now, confirm_days=confirm_days, expiring_days=expiring_days)
    return {fresh.FRESH: OK, fresh.EXPIRING: EXPIRING, fresh.STALE: STALE}.get(state, STALE)


def price_date_of(offer) -> date:
    """Дата цены («от ДД.ММ»): позднее из подтверждения и последнего изменения."""
    from catalog.offer_freshness import reference_moment

    moment = reference_moment(offer)
    return timezone.localdate(moment) if moment is not None else timezone.localdate()


def candidates(
    product_ids: Iterable[int], *, own_company_id: Optional[int], target: Optional[str], seller_company_id=None
) -> dict[int, tuple[list[Option], Any]]:
    """По товару: (действующие цены партнёров от дешёвой к дорогой, последняя истёкшая цена или None).

    `target` — код валюты строки; None — валюта самой цены (перевод не нужен, сравнение всё равно в сумах)."""
    from catalog.models import SupplierOffer
    from catalog.policy import policy_for

    ids = sorted({pid for pid in product_ids if pid})
    if not ids:
        return {}
    today = timezone.localdate()
    now = timezone.now()
    policy = policy_for(seller_company_id or own_company_id)
    rows = list(
        SupplierOffer.objects.filter(product_id__in=ids, is_active=True)
        .exclude(supplier_id=own_company_id)
        .filter(base_price__gt=0)
        .select_related("supplier", "currency")
    )
    codes = {_code(row) for row in rows}
    if target:
        codes.add(target.upper())
    rates = _rates(codes, today)
    target_rate = rates.get(target.upper()) if target else None
    out: dict[int, tuple[list[Option], Any]] = {pid: ([], None) for pid in ids}
    for row in rows:
        options, expired = out[row.product_id]
        if row.valid_until is not None and row.valid_until < today:
            if expired is None or row.valid_until > expired.valid_until:
                out[row.product_id] = (options, row)
            continue
        code = _code(row)
        rate = rates.get(code)
        if rate is None:
            continue  # курса нет — цену не сравнить, молча не берём
        base = (row.base_price * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
        if not target or code == target.upper():
            price, currency = row.base_price.quantize(_CENT, rounding=ROUND_HALF_UP), code
        elif target_rate:
            price, currency = (row.base_price * rate / target_rate).quantize(
                _CENT, rounding=ROUND_HALF_UP
            ), target.upper()
        else:
            continue
        if price <= 0:
            continue
        options.append(
            Option(
                row,
                price,
                currency,
                base,
                _label(
                    row,
                    today=today,
                    now=now,
                    confirm_days=policy.offer_confirm_days,
                    expiring_days=policy.offer_expiring_days,
                ),
                price_date_of(row),
            )
        )
    for pid, (options, _expired) in out.items():
        options.sort(key=lambda o: (o.base, o.offer.valid_until or date.max, o.offer.pk))
    return out


def best(options: list[Option]) -> Optional[Option]:
    return options[0] if options else None


def default_margin(company) -> Decimal:
    """Наценка по умолчанию из настроек «Продажи» компании-продавца; без компании — 0 (наценки нет)."""
    if company is None:
        return Decimal("0")
    value = company.settings.default_margin_percent
    return Decimal(str(value)) if value is not None else Decimal("0")
