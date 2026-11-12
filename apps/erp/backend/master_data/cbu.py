"""Источник «ЦБ»: список валют из открытого JSON ЦБ РУз (исследование 2026-11-11 «Справочники» §B1, §C2; план, PR 5).

Тот же ответ, откуда берутся курсы (`finance.services.fx.fetch_cbu_rates`): 74 строки с буквенным и цифровым кодом,
номиналом и названиями ru, uz (латиница), en. Решение владельца 2026-11-11: все валюты ЦБ загружаются выключенными,
нужные включают; курс приходит по каждой включённой. Источник обновляет названия и цифровой код, кроме полей,
изменённых руками; «действует», порядок и символ не трогает. Валюта, которой больше нет у ЦБ, не удаляется —
получает `in_source = False`. Предохранитель: ответ короче `MIN_CURRENCIES` строк не помечает пропавших.
"""

import datetime
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from django.db import transaction
from django.utils import timezone

from .models import Currency

logger = logging.getLogger(__name__)

SOURCE = "cbu"
SOURCE_NAMES = {"ru": "ЦБ", "uz": "MB", "en": "CBU"}
#: ЦБ отдаёт 74 валюты; заметно меньше — сбой источника, а не закрытие валют.
MIN_CURRENCIES = 50
#: Поля, которые ведёт источник (порядок — как в ответе ЦБ).
SOURCE_FIELDS = ("name", "name_uz", "name_en", "iso_numeric")


@dataclass(frozen=True)
class CbuRow:
    code: str
    iso_numeric: str
    name_ru: str
    name_uz: str
    name_en: str
    nominal: Decimal
    rate: Decimal
    rate_date: Optional[datetime.date]

    @property
    def rate_per_unit(self) -> Decimal:
        """Сум за одну единицу: у ЦБ `Rate` дан за `Nominal` единиц (у рупии — за 10)."""
        return self.rate / self.nominal


def _text(value: Any) -> str:
    return str(value or "").strip()


def parse(payload: Any) -> list[CbuRow]:
    """Строки ответа ЦБ; строка без кода, курса или с номиналом ≤ 0 пропускается с записью в лог."""
    rows: list[CbuRow] = []
    for raw in payload if isinstance(payload, list) else []:
        if not isinstance(raw, dict):
            continue
        code = _text(raw.get("Ccy")).upper()
        try:
            rate = Decimal(_text(raw.get("Rate")))
            nominal = Decimal(_text(raw.get("Nominal")) or "1")
        except InvalidOperation:
            logger.warning("CBU: bad rate or nominal for %s: %r", code, raw)
            continue
        if not code or len(code) != 3 or not rate.is_finite() or rate <= 0 or not nominal.is_finite() or nominal <= 0:
            logger.warning("CBU: skipped row %r", raw)
            continue
        try:
            rate_date = datetime.datetime.strptime(_text(raw.get("Date")), "%d.%m.%Y").date()
        except ValueError:
            rate_date = None
        rows.append(
            CbuRow(
                code=code,
                iso_numeric=_text(raw.get("Code"))[:3],
                name_ru=_text(raw.get("CcyNm_RU"))[:255],
                name_uz=_text(raw.get("CcyNm_UZ"))[:255],
                name_en=_text(raw.get("CcyNm_EN"))[:255],
                nominal=nominal,
                rate=rate,
                rate_date=rate_date,
            )
        )
    return rows


@dataclass(frozen=True)
class SyncSummary:
    added: int
    updated: int
    missing: int


def sync_currencies(rows: Iterable[CbuRow], *, now: Optional[datetime.datetime] = None) -> SyncSummary:
    """Обновить список валют по ответу ЦБ одной транзакцией."""
    rows = list(rows)
    moment = now or timezone.now()
    added = updated = missing = 0
    with transaction.atomic():
        existing = {c.code: c for c in Currency.objects.select_for_update()}
        position = max((c.sort_order for c in existing.values()), default=0)
        for row in rows:
            values = {
                "name": row.name_ru,
                "name_uz": row.name_uz,
                "name_en": row.name_en,
                "iso_numeric": row.iso_numeric,
            }
            current = existing.get(row.code)
            if current is None:
                position += 10
                Currency.objects.create(
                    code=row.code,
                    is_active=False,  # решение владельца 2026-11-11: новые валюты ЦБ выключены
                    sort_order=position,
                    source=SOURCE,
                    synced_at=moment,
                    in_source=True,
                    **{**values, "name": row.name_ru or row.code},
                )
                added += 1
                continue
            manual = set(current.manual_fields or [])
            changed = [f for f, v in values.items() if v and f not in manual and getattr(current, f) != v]
            for field in changed:
                setattr(current, field, values[field])
            current.source, current.synced_at, current.in_source = SOURCE, moment, True
            current.save(update_fields=[*changed, "source", "synced_at", "in_source"])
            updated += bool(changed)
        if len(rows) >= MIN_CURRENCIES:
            gone = Currency.objects.filter(source=SOURCE, in_source=True).exclude(code__in=[r.code for r in rows])
            for currency in gone:
                currency.in_source = False
                currency.save(update_fields=["in_source"])
                missing += 1
        elif rows:
            logger.warning("CBU: only %s currencies in the answer — missing ones are not marked", len(rows))
    return SyncSummary(added=added, updated=updated, missing=missing)
