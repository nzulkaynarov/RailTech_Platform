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

REQUEST_PREFIX = "ЗВ"
PROJECT_PREFIX = "ПР"
_WIDTH = 3
_LATIN = {"zv": REQUEST_PREFIX, "pr": PROJECT_PREFIX}
_QUERY = re.compile(r"(?P<prefix>[^\W\d_]{2})?[\s\-–—/]*(?P<year>\d{4})[\s\-–—/]+(?P<seq>\d{1,9})")


def format_number(prefix: str, year: int, seq: int) -> str:
    return f"{prefix}-{year:04d}-{seq:0{_WIDTH}d}"


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
    deal.number = format_number(REQUEST_PREFIX, year, seq)


def promote_to_project(deal) -> bool:
    """Заявка → проект (КП принято клиентом): `is_project` и номер ПР с тем же NNN. Возвращает, изменился ли номер;
    сохраняет только эти поля."""
    fields: dict = {}
    if not deal.is_project:
        deal.is_project = fields["is_project"] = True
    number = (
        format_number(PROJECT_PREFIX, deal.number_year, deal.number_seq) if deal.number_seq and deal.number_year else ""
    )
    renumbered = bool(number) and deal.number != number
    if renumbered:
        deal.number = fields["number"] = number
    if fields:
        type(deal).objects.filter(pk=deal.pk).update(**fields)
    return renumbered


def stage_of(number: str) -> str:
    """Стадия сделки по её номеру — `request` (заявка, до принятия КП) или `project`: единственное место, где смысл
    префикса известен (здесь же он выдаётся), — экраны и портал читают стадию отсюда, а не разбирают номер сами.
    Номер без префикса заявки (старые сделки `D-<id>`) — проект, как раньше."""
    return "request" if (number or "").startswith(f"{REQUEST_PREFIX}-") else "project"


def parse_query(text: str) -> Optional[tuple[int, int]]:
    """`ЗВ-2026-104`, `ПР-2026-104`, `zv 2026 104`, `2026-104` → (2026, 104); не номер — None."""
    match = _QUERY.fullmatch((text or "").strip())
    if match is None:
        return None
    prefix = (match["prefix"] or "").casefold()
    if prefix and _LATIN.get(prefix, prefix.upper()) not in (REQUEST_PREFIX, PROJECT_PREFIX):
        return None
    return int(match["year"]), int(match["seq"])
