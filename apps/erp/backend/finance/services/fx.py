"""Курсы валют к UZS — единая точка истины ERP (M1-ERP-08; перенесено из `master_data.fx`).

Откуда курсы: справочник `core.ExchangeRate` (1 единица валюты = `rate_to_uzs` сум). Его наполняет
ежедневная задача Beat `master_data.tasks.refresh_exchange_rates` из открытого JSON ЦБ РУз
(`fetch_cbu_rates`, источник `CBU`); оператор может ввести курс вручную (`set_manual_rate`, источник `MANUAL`,
экран «Компания» Платформы, W13C-F6) — на случай, когда автозагрузка не сработала. Ручной курс на дату автозагрузка
не перетирает (`fetch_cbu_rates`): она пишет в журнал, что не применила курс ЦБ.
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

        from core.tenant import own_company_id

        try:
            company_id = own_company_id()  # нужен только id: строку компании читать незачем
        except ImproperlyConfigured:
            logger.warning(
                "FX: own company is ambiguous (set OWN_COMPANY_ID) — using FX_RATE_MAX_AGE_DAYS=%s", fallback
            )
            return fallback
    else:
        company_id = company.pk
    if company_id is None:
        return fallback
    value = CompanySettings.objects.filter(company_id=company_id).values_list("fx_rate_max_age_days", flat=True).first()
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


def resolve_rate(
    currency_code, on_date: Optional[datetime.date] = None, *, max_age_days: Optional[int] = None
) -> Optional[ResolvedRate]:
    """Курс валюты к UZS на дату `on_date` (по умолчанию — бизнес-сегодня, Ташкент).

    Самая поздняя строка справочника с `rate_date <= on_date` не старше лимита возраста; нет такой — `None`
    (правило «курса нет»). UZS — 1 с источником BASE.

    Лимит — `max_rate_age_days()` (настройка своей компании, FIX-41): это 1–2 запроса на вызов. Кто спрашивает курс по
    нескольким валютам подряд, читает лимит один раз и передаёт `max_age_days` (FIX-54, F-15); глобального кэша нет —
    правка настроек действует сразу.
    """
    from core.models import ExchangeRate

    code = normalize_code(currency_code)
    on_date = on_date or timezone.localdate()
    if code == BASE_CURRENCY:
        return ResolvedRate(code, Decimal("1"), on_date, RateSource.BASE)
    oldest = on_date - datetime.timedelta(days=max_rate_age_days() if max_age_days is None else max_age_days)
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


def _apply_cbu_rate(currency, rate_date: datetime.date, rate: Decimal) -> bool:
    """Записать курс ЦБ на дату, не трогая ручной. `True` — курс записан.

    Проверка «стоит MANUAL» и запись — под одной блокировкой строки (`select_for_update`): ручной ввод,
    попавший между ними, не перетрётся. Новую строку создаёт `get_or_create` (при гонке за уникальный ключ
    он возвращает чужую строку, а не перезаписывает её): сначала создание, и только потом — обновление
    существующей строки под блокировкой.
    """
    from django.db import transaction

    from core.models import ExchangeRate

    row, created = ExchangeRate.objects.get_or_create(
        currency=currency, rate_date=rate_date, defaults={"rate_to_uzs": rate, "source": RateSource.CBU}
    )
    if created:
        return True
    with transaction.atomic():
        row = ExchangeRate.objects.select_for_update().select_related("currency").get(pk=row.pk)
        if (row.source or "").upper() == RateSource.MANUAL:
            _note_auto_skipped(row, rate)
            return False
        row.rate_to_uzs = rate
        row.source = RateSource.CBU
        row.save(update_fields=["rate_to_uzs", "source"])
    return True


def fetch_cbu_rates(timeout: int = 15) -> int:
    """Забрать текущие курсы ЦБ РУз и обновить `ExchangeRate` (источник CBU). Возвращает число строк.

    JSON ЦБ: по строке на валюту `{"Ccy": "USD", "Rate": "12013.52", "Date": "26.06.2026", ...}`,
    где Rate — сум за 1 единицу. Вызывается только задачей Beat (не в пути запроса).
    """
    import httpx

    from core.models import Currency

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
        if _apply_cbu_rate(currency, rate_date, rate):
            upserted += 1
    return upserted


def get_rate_to_uzs(currency_code: str, on_date=None, *, max_age_days: Optional[int] = None) -> Optional[Decimal]:
    """Курс к UZS на дату (UZS = 1) по правилу `resolve_rate`; нет курса — None."""
    resolved = resolve_rate(currency_code, on_date, max_age_days=max_age_days)
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


# --- ручной ввод курса (W13C-F6) ------------------------------------------------------------------------------------

#: Коды событий в журнале ERP (`crm.ActivityLog`, префикс `admin.`): их читает `fx_journal`.
MANUAL_RATE_EVENT = "admin.exchange_rate.manual"
AUTO_SKIPPED_EVENT = "admin.exchange_rate.auto_skipped"
FX_JOURNAL_EVENTS = (MANUAL_RATE_EVENT, AUTO_SKIPPED_EVENT)
FX_ENTITY_TYPE = "core.exchangerate"  # метка модели — как у `AuditedWriteMixin`

#: Курс — не больше миллиарда сум за единицу (опечатка в порядке не должна уйти в КП) и 6 знаков после запятой.
MAX_MANUAL_RATE = Decimal("1000000000")
MANUAL_BACKFILL_DAYS = 366  # курс на дату старше года — почти наверняка опечатка в годе


def _rate_snapshot(row) -> dict:
    return {"rate_to_uzs": rate_to_str(row.rate_to_uzs), "source": (row.source or RateSource.CBU).upper()}


def _note_auto_skipped(pinned, cbu_rate: Decimal) -> None:
    """Автозагрузка встретила ручной курс на ту же дату: ручной остаётся, различие — в журнал (один раз)."""
    from core.audit import log_admin_action
    from crm.models import ActivityLog

    if rate_to_str(cbu_rate) == rate_to_str(pinned.rate_to_uzs):
        return  # курсы совпали — сообщать нечего
    logger.warning(
        "FX: CBU rate %s for %s @ %s not applied — manual rate %s is kept",
        cbu_rate,
        pinned.currency_id,
        pinned.rate_date,
        pinned.rate_to_uzs,
    )
    seen = ActivityLog.objects.filter(
        entity_type=FX_ENTITY_TYPE,
        entity_id=pinned.pk,
        event_code=AUTO_SKIPPED_EVENT,
        after_data__rate_to_uzs=rate_to_str(cbu_rate),
    ).exists()
    if seen:
        return
    code = pinned.currency.code
    log_admin_action(
        entity_type=FX_ENTITY_TYPE,
        entity_id=pinned.pk,
        action=f"Курс {code} на {pinned.rate_date}: автокурс ЦБ не применён, оставлен ручной",
        detail=f"ЦБ {rate_to_str(cbu_rate)}, ручной {rate_to_str(pinned.rate_to_uzs)}",
        level="WARNING",
        before=_rate_snapshot(pinned),
        after={"rate_to_uzs": rate_to_str(cbu_rate), "source": RateSource.CBU},
        event_code=AUTO_SKIPPED_EVENT,
        event_params={"currency": code, "rate_date": pinned.rate_date.isoformat()},
    )


def set_manual_rate(*, currency_code, rate_date, rate, actor, today: Optional[datetime.date] = None):
    """Курс валюты к UZS на дату — вручную (источник `MANUAL`), с записью в журнал ERP.

    Возвращает `(строка ExchangeRate, None)` или `(None, код ошибки)`:
    `FX_CURRENCY_UNSUPPORTED`, `FX_RATE_INVALID` (не число, ≤ 0, больше потолка, больше 6 знаков),
    `FX_RATE_DATE_INVALID`, `FX_RATE_DATE_IN_FUTURE`, `FX_RATE_DATE_TOO_OLD`.

    Строка на (валюта, дата) уникальна: ручной ввод заменяет и курс ЦБ, и прежний ручной — прежнее значение и его
    источник остаются в журнале (`before`). Повтор того же ручного значения ничего не пишет.
    """
    from django.db import transaction

    from core.audit import log_admin_action
    from core.models import Currency, ExchangeRate

    code = normalize_code(currency_code)
    if code not in TRACKED_CURRENCIES:
        return None, "FX_CURRENCY_UNSUPPORTED"
    currency = Currency.objects.filter(code=code).first()
    if currency is None:
        return None, "FX_CURRENCY_UNSUPPORTED"

    parsed_rate = parse_positive_rate(rate)
    if (
        parsed_rate is None
        or parsed_rate >= MAX_MANUAL_RATE
        or parsed_rate != parsed_rate.quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
    ):
        return None, "FX_RATE_INVALID"

    if isinstance(rate_date, str):
        try:
            rate_date = datetime.date.fromisoformat(rate_date.strip())
        except ValueError:
            return None, "FX_RATE_DATE_INVALID"
    if not isinstance(rate_date, datetime.date):
        return None, "FX_RATE_DATE_INVALID"
    today = today or timezone.localdate()
    if rate_date > today:
        return None, "FX_RATE_DATE_IN_FUTURE"
    if rate_date < today - datetime.timedelta(days=MANUAL_BACKFILL_DAYS):
        return None, "FX_RATE_DATE_TOO_OLD"

    with transaction.atomic():
        existing = ExchangeRate.objects.select_for_update().filter(currency=currency, rate_date=rate_date).first()
        before = _rate_snapshot(existing) if existing is not None else None
        if existing is not None and before["source"] == RateSource.MANUAL and existing.rate_to_uzs == parsed_rate:
            return existing, None
        row, _created = ExchangeRate.objects.update_or_create(
            currency=currency,
            rate_date=rate_date,
            defaults={"rate_to_uzs": parsed_rate, "source": RateSource.MANUAL},
        )
        log_admin_action(
            entity_type=FX_ENTITY_TYPE,
            entity_id=row.pk,
            action=f"Курс {code} на {rate_date} введён вручную",
            detail=str(row),
            actor=actor,
            before=before,
            after=_rate_snapshot(row),
            event_code=MANUAL_RATE_EVENT,
            event_params={"currency": code, "rate_date": rate_date.isoformat()},
        )
    return row, None


def fx_journal(currency_code="USD", limit: int = 20):
    """Последние записи журнала курса: ручные вводы и случаи «автокурс не применён» (новые первыми)."""
    from crm.models import ActivityLog

    return list(
        ActivityLog.objects.filter(
            entity_type=FX_ENTITY_TYPE,
            event_code__in=FX_JOURNAL_EVENTS,
            event_params__currency=normalize_code(currency_code),
        )
        .select_related("user")
        .order_by("-timestamp", "-id")[:limit]
    )
