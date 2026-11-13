"""Номер заявки ЗВ-ГГГГ-NNN и проекта ПР-ГГГГ-NNN (SPEC-v3 §2.2, ERP-09, docs/architecture/integration-map.md §5).

* `assign(deal)` — новая сделка получает NNN из счётчика своего года (`DealNumberCounter`): строка года вставляется,
  если её нет (`ON CONFLICT DO NOTHING`), и берётся `SELECT … FOR UPDATE` — параллельные создатели ждут друг друга, номер
  выдаётся без пропусков (откат транзакции возвращает и номер). Вызывается из `Deal.save` в одной транзакции со вставкой.
  Уникальность `(number_year, number_seq)` — последний рубеж.
* `promote_to_project(deal)` — после принятия КП клиентом заявка становится проектом: префикс `ПР`, NNN тот же.
* `search_terms(text)` — строка поиска сделок по номеру: `ЗВ-2026-104`, `пр 2026 104`, `zv-2026-104` ищут один NNN
  независимо от префикса и ширины.

Год — по часовому поясу компании (`TIME_ZONE`, Asia/Tashkent): заявка 1 января 00:30 по Ташкенту — новый год.
"""

from __future__ import annotations

import re
from typing import Optional

from django.db import transaction
from django.utils import timezone

# Префиксы до 2026-11-13 (SPEC-v3 §2.2): выданные номера не меняются, поиск их находит. Новые — из схемы нумерации
# («Настройки · Нумерация», виды REQ и PRJ, по умолчанию RQ и PRJ; задача «Н»).
REQUEST_PREFIX = "ЗВ"
PROJECT_PREFIX = "ПР"
_LEGACY = {"зв", "пр", "zv", "pr"}
_QUERY = re.compile(r"(?P<prefix>[^\W\d_]{1,8})?[\s\-–—/]*(?P<year>\d{4})[\s\-–—/]+(?P<seq>\d{1,9})")


def _label(kind: str) -> str:
    from crm.services.numbering import type_label

    return type_label(kind)


def format_number(prefix: str, year: int, seq: int) -> str:
    from crm.services.numbering import own_format_number

    return own_format_number(prefix, year, seq)


def _next_seq(year: int) -> int:
    from sales.models import DealNumberCounter

    DealNumberCounter.objects.bulk_create([DealNumberCounter(year=year)], ignore_conflicts=True)
    counter = DealNumberCounter.objects.select_for_update().get(year=year)
    counter.last_value += 1
    counter.save(update_fields=["last_value"])
    return counter.last_value


@transaction.atomic
def assign(deal) -> None:
    """Номер ЗВ новой сделке. Вызывать внутри транзакции вставки (`Deal.save`): блокировка счётчика держится до конца
    внешней транзакции, откат вставки возвращает и номер."""
    year = timezone.localdate().year
    seq = _next_seq(year)
    deal.number_year, deal.number_seq = year, seq
    deal.number = format_number(_label("REQ"), year, seq)


def promote_to_project(deal) -> bool:
    """Заявка → проект (КП принято клиентом): `is_project` и номер ПР с тем же NNN. Возвращает, изменился ли номер;
    сохраняет только эти поля."""
    fields: dict = {}
    if not deal.is_project:
        deal.is_project = fields["is_project"] = True
    number = (
        format_number(_label("PRJ"), deal.number_year, deal.number_seq) if deal.number_seq and deal.number_year else ""
    )
    renumbered = bool(number) and deal.number != number
    if renumbered:
        deal.number = fields["number"] = number
    if fields:
        type(deal).objects.filter(pk=deal.pk).update(**fields)
    return renumbered


def stage_of(deal) -> str:
    """Стадия сделки — `request` (заявка, до принятия КП) или `project`: полем `is_project`, а не по префиксу номера
    (префиксы задаёт владелец в настройках нумерации, задача «Н»)."""
    return "project" if deal.is_project else "request"


def parse_query(text: str) -> Optional[tuple[int, int]]:
    """`RQ-2026-104`, `PRJ-2026-104`, `ЗВ-2026-104`, `zv 2026 104`, `2026-104` → (2026, 104); не номер сделки — None.
    Префикс — нынешние метки заявки и проекта из схемы или прежние ЗВ/ПР; регистр не важен."""
    match = _QUERY.fullmatch((text or "").strip())
    if match is None:
        return None
    prefix = (match["prefix"] or "").casefold()
    if prefix and prefix not in _LEGACY | {_label("REQ").casefold(), _label("PRJ").casefold()}:
        return None
    return int(match["year"]), int(match["seq"])
