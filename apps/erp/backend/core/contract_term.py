"""Срок договора (ДС-1, решение владельца 2026-11-25): чистые правила без базы данных.

Правило — настройка компании (`CompanySettings.contract_*`) или шаблона договора (`DocumentTemplate.term_rule`,
`renewal_mode`, `notice_days`); здесь только арифметика дат, которую вызывают подписание, ночная задача и проверка
окончания срока. Базы, пользователей и времени здесь нет: «сегодня» приходит параметром.

Правила, которые закреплены кодом (не настройки):
* срок и «последний день уведомления» вычисляются, вручную не вводятся;
* договор, подписанный начиная с дня границы декабря, получает срок до конца СЛЕДУЮЩЕГО года;
* последний день уведомления не бывает раньше дня подписания: иначе срок сдвигается на следующий период;
* 12 месяцев с 29 февраля заканчиваются 27 февраля: годовщина 29 февраля в невисокосном году — 28 февраля.
"""

import calendar
import datetime as dt
from dataclasses import dataclass
from typing import Optional

from django.db import models
from django.utils.translation import gettext_lazy as _


class ContractTermRule(models.TextChoices):
    CALENDAR_YEAR = "calendar_year", _("До 31 декабря")
    TWELVE_MONTHS = "twelve_months", _("12 месяцев с подписания")
    OPEN = "open", _("Без срока")


class ContractRenewalMode(models.TextChoices):
    AUTO = "auto", _("Продлевается сам")
    BY_AGREEMENT = "by_agreement", _("Продлевается соглашением")
    NONE = "none", _("Не продлевается")


class ContractExpiredAction(models.TextChoices):
    BLOCK = "block", _("Не создавать новые КП и сделки")
    WARN = "warn", _("Только предупреждать")


class DeclinedBy(models.TextChoices):
    COMPANY = "company", _("Мы")
    CLIENT = "client", _("Контрагент")


@dataclass(frozen=True)
class Term:
    valid_from: dt.date
    valid_until: Optional[dt.date]
    last_notice_date: Optional[dt.date]


def _anniversary(day: dt.date, years: int = 1) -> dt.date:
    year = day.year + years
    if day.month == 2 and day.day == 29 and not calendar.isleap(year):
        return dt.date(year, 2, 28)
    return dt.date(year, day.month, day.day)


def _december_boundary(year: int, boundary_day: int) -> dt.date:
    return dt.date(year, 12, min(max(boundary_day, 1), 31))


def period_end_after(start: dt.date, rule: str) -> Optional[dt.date]:
    """Последний день срока, начинающегося в `start` (для продления: день после прежнего окончания)."""
    if rule == ContractTermRule.TWELVE_MONTHS:
        return _anniversary(start) - dt.timedelta(days=1)
    if rule == ContractTermRule.CALENDAR_YEAR:
        return dt.date(start.year, 12, 31)
    return None


def first_term(signed_on: dt.date, rule: str, *, notice_days: int, boundary_day: int = 1) -> Term:
    """Первый срок договора, подписанного `signed_on`."""
    if rule == ContractTermRule.OPEN:
        return Term(signed_on, None, None)
    if rule == ContractTermRule.CALENDAR_YEAR:
        year = signed_on.year
        if signed_on >= _december_boundary(year, boundary_day):
            year += 1
        until = dt.date(year, 12, 31)
        while until - dt.timedelta(days=notice_days) < signed_on:
            until = dt.date(until.year + 1, 12, 31)
        return Term(signed_on, until, until - dt.timedelta(days=notice_days))
    until = period_end_after(signed_on, rule)
    assert until is not None
    while until - dt.timedelta(days=notice_days) < signed_on:
        until = period_end_after(until + dt.timedelta(days=1), rule) or until
    return Term(signed_on, until, until - dt.timedelta(days=notice_days))


def next_term(valid_until: dt.date, rule: str, *, notice_days: int, today: dt.date) -> Term:
    """Срок, которым продлевается договор, закончившийся `valid_until`.

    Если ночная задача долго не работала, пропущенные периоды закрываются подряд: результат всегда кончается не раньше
    `today`, поэтому повторный запуск в тот же день срок не меняет (идемпотентность)."""
    start = valid_until + dt.timedelta(days=1)
    until = period_end_after(start, rule)
    if until is None:
        return Term(start, None, None)
    while until < today:
        start = until + dt.timedelta(days=1)
        until = period_end_after(start, rule) or until
    return Term(start, until, until - dt.timedelta(days=notice_days))


def term_from_today(today: dt.date, rule: str, *, notice_days: int, boundary_day: int = 1) -> Term:
    """Срок после ручного продления (доп. соглашение, возобновление): как у договора, подписанного сегодня."""
    return first_term(today, rule, notice_days=notice_days, boundary_day=boundary_day)
