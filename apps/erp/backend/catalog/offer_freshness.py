"""Свежесть цены поставщика (PART-2): «подтверждено», «устарела», «истекает», «срок истёк».

Цены поставщика не модерируются (закупочные данные, ADR-0022 п. 4): партнёр сам подтверждает, что они действуют, а мы
показываем ему и сотруднику, какие цены давно не подтверждались. Эталон — Odoo `product.supplierinfo` (цена со сроком
«с / до» без согласования) и SAP Ariba (поставщик подтверждает каталог перед периодом).

Правила (детерминированные, без модели):
- «срок истёк» — `valid_until` раньше сегодняшнего дня; подтвердить такую цену нельзя, нужен новый прайс;
- «устарела» — не подтверждена дольше `offer_confirm_days` (настройка компании, по умолчанию 30) дней; точкой отсчёта
  служит позднее из даты подтверждения и даты последнего изменения цены;
- «истекает» — `valid_until` через `offer_expiring_days` (настройка компании, по умолчанию 14; задача «Н3c») дней или раньше;
- иначе «актуальна».
Приоритет: срок истёк > устарела > истекает > актуальна.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .constants import DEFAULT_OFFER_EXPIRING_DAYS

FRESH = "fresh"
EXPIRING = "expiring"
STALE = "stale"
EXPIRED = "expired"
FRESHNESS_CODES = (FRESH, EXPIRING, STALE, EXPIRED)


def reference_moment(offer) -> datetime | None:
    """С какого момента считаем «давность»: позднее из подтверждения и последнего изменения цены.

    Подтверждение не двигает `updated_at` (его ставит массовое обновление), поэтому новая цена, внесённая сотрудником или
    загрузкой, освежает предложение, а подтверждение партнёра — тоже."""
    moments = [moment for moment in (offer.confirmed_at, offer.updated_at) if moment is not None]
    return max(moments) if moments else offer.created_at


def freshness(
    offer, *, today: date, now: datetime, confirm_days: int, expiring_days: int = DEFAULT_OFFER_EXPIRING_DAYS
) -> str:
    valid_until = offer.valid_until
    if valid_until is not None and valid_until < today:
        return EXPIRED
    since = reference_moment(offer)
    if since is not None and now - since > timedelta(days=confirm_days):
        return STALE
    if valid_until is not None and valid_until <= today + timedelta(days=expiring_days):
        return EXPIRING
    return FRESH
