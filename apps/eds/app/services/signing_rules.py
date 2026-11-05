"""Инварианты основания полномочия подписи (ADR-0024 п. 1; ГК РУз ст. 134, 138, 139) — чистые функции без базы.

* Доверенность: номер, дата выдачи и срок обязательны; срок не позже даты выдачи плюс 3 года (ст. 139); действует не
  ранее выдачи.
* Приказ: номер и дата обязательны (в подписи «приказ № … от …»).
* Устав: номера нет; срок необязателен (полномочие органа действует, пока он в должности).
* Пересечения полномочий допустимы: устав и доверенность у одного человека, разные лимиты — не ошибка.
* Лимит: сумма и валюта — парой; пусто — без лимита.

Возвращают словарь «поле → текст ошибки» для `invalid_fields`; пусто — всё в порядке.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

from app.models.signing import BASES, BASIS_CHARTER, BASIS_POWER_OF_ATTORNEY

MAX_POWER_OF_ATTORNEY_YEARS = 3
_VAKOLAT_HOST = "vakolat.uz"
MAX_NOTE = 2000


@dataclass(frozen=True, slots=True)
class Terms:
    """Условия полномочия, как их проверяют: что, на каком основании, на какой срок."""

    kinds: tuple[str, ...]
    basis: str
    basis_number: str | None
    basis_date: date | None
    valid_from: date
    valid_to: date | None
    limit_amount: Decimal | None
    limit_currency: str | None
    vakolat_url: str | None = None


def add_years(day: date, years: int) -> date:
    """Та же дата через `years` лет; 29 февраля в невисокосном году — 28 февраля (как в PostgreSQL)."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def power_of_attorney_deadline(issued: date) -> date:
    """Последний допустимый день действия доверенности, выданной `issued`."""
    return add_years(issued, MAX_POWER_OF_ATTORNEY_YEARS)


def is_vakolat_url(value: str) -> bool:
    """Ссылка на реестр доверенностей Vakolat.uz: https и домен `vakolat.uz` (или поддомен)."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == _VAKOLAT_HOST or host.endswith(f".{_VAKOLAT_HOST}"))


def check(terms: Terms) -> dict[str, str]:
    """Нарушения условий: ключ — поле запроса, значение — что исправить (по-русски, сотруднику)."""
    bad: dict[str, str] = {}
    if not terms.kinds:
        bad["kinds"] = "Выберите хотя бы один вид документа."
    if len(set(terms.kinds)) != len(terms.kinds):
        bad["kinds"] = "Вид документа указан дважды."
    if terms.basis not in BASES:
        bad["basis"] = "Выберите основание: устав, приказ или доверенность."
        return bad
    if (terms.limit_amount is None) != (terms.limit_currency is None):
        bad["limit_currency" if terms.limit_amount is not None else "limit_amount"] = (
            "Лимит задаётся суммой и валютой вместе."
        )
    if terms.limit_amount is not None and terms.limit_amount <= 0:
        bad["limit_amount"] = "Лимит должен быть больше нуля."
    if terms.valid_to is not None and terms.valid_to < terms.valid_from:
        bad["valid_to"] = "Срок окончания раньше начала."
    if terms.vakolat_url is not None and not is_vakolat_url(terms.vakolat_url):
        bad["vakolat_url"] = "Ссылка должна вести на vakolat.uz (https)."
    bad.update(_basis_problems(terms))
    return bad


def _basis_problems(terms: Terms) -> dict[str, str]:
    bad: dict[str, str] = {}
    if terms.basis == BASIS_CHARTER:
        if terms.basis_number:
            bad["basis_number"] = "У полномочия по уставу номера нет."
        return bad
    label = "доверенности" if terms.basis == BASIS_POWER_OF_ATTORNEY else "приказа"
    if not terms.basis_number:
        bad["basis_number"] = f"Укажите номер {label}."
    if terms.basis_date is None:
        bad["basis_date"] = f"Укажите дату {label}."
    if terms.basis != BASIS_POWER_OF_ATTORNEY:
        return bad
    if terms.valid_to is None:
        bad["valid_to"] = "Укажите срок доверенности: не более 3 лет со дня выдачи."
    if terms.basis_date is not None:
        if terms.valid_from < terms.basis_date:
            bad["valid_from"] = "Доверенность не может действовать раньше даты выдачи."
        deadline = power_of_attorney_deadline(terms.basis_date)
        if terms.valid_to is not None and terms.valid_to > deadline:
            bad["valid_to"] = f"Доверенность выдаётся не более чем на 3 года: до {deadline:%d.%m.%Y} (ГК, ст. 139)."
    return bad


__all__ = ["Terms", "add_years", "check", "is_vakolat_url", "power_of_attorney_deadline"]
