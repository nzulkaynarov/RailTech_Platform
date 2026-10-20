"""Курсы валют к UZS — единая точка истины ERP (M1-ERP-08; перенесено из `master_data.fx`).

Откуда курсы: справочник `core.ExchangeRate` (1 единица валюты = `rate_to_uzs` сум). Его наполняет
ежедневная задача Beat `master_data.tasks.refresh_exchange_rates` из открытого JSON ЦБ РУз
(`fetch_cbu_rates`, источник `CBU`); инженер может добавить строку в админке (источник `MANUAL`).
Договорной курс конкретного КП — не здесь: он живёт на самом КП (`Quote.fx_manual`, право
`finance.rates`, см. `sales.services.quote_fx`).

Правило «курса нет» (по рекомендации, Odoo / SAP B1 — курс документа на его дату):
курс на дату D — строка с самой поздней `rate_date <= D`, но не старше `FX_RATE_MAX_AGE_DAYS`
календарных дней (по умолчанию 7: ЦБ не публикует курс в выходные и праздники, неделя покрывает
длинные праздники). Старее — курса нет (`None`), вызывающий поднимает `FX_RATE_MISSING`.
UZS — базовая валюта, курс 1.
"""

import datetime
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

BASE_CURRENCY = "UZS"
CBU_URL = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/"
# Валюты, в которых реально идут закупки (UZS — база = 1, не хранится).
TRACKED_CURRENCIES = {"USD", "EUR", "RUB"}

# Деньги — копейки, курс — 6 знаков (как `ExchangeRate.rate_to_uzs`), округление — к ближайшему, 0.5 вверх.
MONEY_QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.000001")


class RateSource:
    """Откуда взят курс (строка в API и в снимке КП)."""

    BASE = "BASE"  # UZS к самому себе
    CBU = "CBU"  # ЦБ РУз (задача Beat)
    MANUAL = "MANUAL"  # строка справочника, внесённая вручную
    OVERRIDE = "OVERRIDE"  # договорной курс КП (finance.rates, с причиной)


@dataclass(frozen=True)
class ResolvedRate:
    currency: str
    rate: Decimal
    rate_date: Optional[datetime.date]
    source: str


def normalize_code(currency_code) -> str:
    return (currency_code or "").strip().upper() or BASE_CURRENCY


def is_base(currency_code) -> bool:
    return normalize_code(currency_code) == BASE_CURRENCY


def max_rate_age_days(company=None) -> int:
    """Лимит возраста курса в днях: настройка СВОЕЙ компании (FIX-41, F-3).

    `company` не передана — компания-владелец ERP (`core.tenant.own_company`). Переменная окружения
    `FX_RATE_MAX_AGE_DAYS` — только запасное значение: когда своей компании ещё нет, у неё нет строки
    настроек или настройка двусмысленна (две «своих» компании без `OWN_COMPANY_ID`). Строка чужой
    компании никогда не используется.
    """
    from parties.models import CompanySettings

    fallback = int(getattr(settings, "FX_RATE_MAX_AGE_DAYS", 7))
    if company is None:
        from django.core.exceptions import ImproperlyConfigured

        from core.tenant import own_company

        try:
            company = own_company()
        except ImproperlyConfigured:
            logger.warning(
                "FX: own company is ambiguous (set OWN_COMPANY_ID) — using FX_RATE_MAX_AGE_DAYS=%s", fallback
            )
            return fallback
    if company is None:
        return fallback
    value = CompanySettings.objects.filter(company_id=company.pk).values_list("fx_rate_max_age_days", flat=True).first()
    return int(value) if value is not None else fallback


def rate_to_str(rate: Decimal) -> str:
    """Курс строкой без хвостовых нулей: «12650.5», «12000» (так курс лежит в снимке КП)."""
    quantized = Decimal(rate).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
    text = format(quantized.normalize(), "f")
    return text


def parse_positive_rate(value) -> Optional[Decimal]:
    """Курс из строки/числа — Decimal только если строго > 0, иначе None (ноль/минус/мусор не курс)."""
    if value in (None, ""):
        return None
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not rate.is_finite() or rate <= 0:
        return None
    return rate


def resolve_rate(currency_code, on_date: Optional[datetime.date] = None) -> Optional[ResolvedRate]:
    """Курс валюты к UZS на дату `on_date` (по умолчанию — бизнес-сегодня, Ташкент).

    Самая поздняя строка справочника с `rate_date <= on_date` не старше `FX_RATE_MAX_AGE_DAYS`;
    нет такой — `None` (правило «курса нет»). UZS — 1 с источником BASE.
    """
    from core.models import ExchangeRate

    code = normalize_code(currency_code)
    on_date = on_date or timezone.localdate()
    if code == BASE_CURRENCY:
        return ResolvedRate(code, Decimal("1"), on_date, RateSource.BASE)
    oldest = on_date - datetime.timedelta(days=max_rate_age_days())
    row = (
        ExchangeRate.objects.filter(currency__code=code, rate_date__lte=on_date, rate_date__gte=oldest)
        .order_by("-rate_date")
        .first()
    )
    if row is None or parse_positive_rate(row.rate_to_uzs) is None:
        return None
    source = (row.source or RateSource.CBU).upper()
    return ResolvedRate(code, Decimal(row.rate_to_uzs), row.rate_date, source)


def convert_to_base(amount, rate) -> Decimal:
    """Сумма в валюте × курс → сумы, округление до копейки (0.5 вверх)."""
    return (Decimal(str(amount)) * Decimal(str(rate))).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def fetch_cbu_rates(timeout: int = 15) -> int:
    """Забрать текущие курсы ЦБ РУз и обновить `ExchangeRate` (источник CBU). Возвращает число строк.

    JSON ЦБ: по строке на валюту `{"Ccy": "USD", "Rate": "12013.52", "Date": "26.06.2026", ...}`,
    где Rate — сум за 1 единицу. Вызывается только задачей Beat (не в пути запроса).
    """
    import httpx

    from core.models import Currency, ExchangeRate

    response = httpx.get(CBU_URL, timeout=timeout)
    response.raise_for_status()
    upserted = 0
    for row in response.json():
        code = (row.get("Ccy") or "").upper()
        if code not in TRACKED_CURRENCIES:
            continue
        try:
            rate = Decimal(str(row.get("Rate")))
        except (InvalidOperation, TypeError):
            logger.warning("FX: bad rate for %s: %r", code, row.get("Rate"))
            continue
        try:
            rate_date = datetime.datetime.strptime(row.get("Date"), "%d.%m.%Y").date()
        except (ValueError, TypeError):
            rate_date = timezone.localdate()
        currency = Currency.objects.filter(code=code).first()
        if not currency:
            continue
        ExchangeRate.objects.update_or_create(
            currency=currency, rate_date=rate_date, defaults={"rate_to_uzs": rate, "source": RateSource.CBU}
        )
        upserted += 1
    return upserted


def get_rate_to_uzs(currency_code: str, on_date=None) -> Optional[Decimal]:
    """Курс к UZS на дату (UZS = 1) по правилу `resolve_rate`; нет курса — None."""
    resolved = resolve_rate(currency_code, on_date)
    return resolved.rate if resolved else None


def convert_to_uzs(amount, currency_code: str, rate=None) -> Optional[Decimal]:
    """`amount` в `currency_code` → UZS (без округления; `rate` вручную побеждает справочник).

    Нет курса и не передан вручную — None.
    """
    amount = Decimal(str(amount))
    if rate is None:
        rate = get_rate_to_uzs(currency_code)
    if rate is None:
        return None
    return amount * Decimal(str(rate))
