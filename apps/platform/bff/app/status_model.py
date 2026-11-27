"""Одна модель статуса `{state, checked_at, source, live}` (НАСТ-П1, аудит Настроек §6.2).

Единственное место, где факты превращаются в слово «Работает» или его отсутствие.
«Состояние», карточки «Сервисов», шаги мастера и счётчик готовности читают этот ответ
и не решают сами. Правила:

- «Работает» — только по живой проверке не старше `STALE_AFTER`; сохранённые настройки
  без проверки — «Настроено, не проверено» (`not_verified`); проверка старше порога —
  «Нет свежих данных» (`stale`);
- не ответила часть данных — «Не удалось проверить» (`unknown`), никогда не «Работает»;
  найденная проблема при этом остаётся проблемой (`attention` / `broken`);
- `checked_at` — время самой старой проверки, на которой держится слово «Работает»;
  у проблемы — самой свежей;
- `source`: `check` — проба сервиса, `counters` — счётчики в базе (связи не проверяют),
  `report` — отчёт, собранный сейчас, `none` — данных нет.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Тяжёлые проверки CRM идут раз в 15 минут; три пропущенных прохода подряд — данные устарели.
STALE_AFTER = timedelta(minutes=45)

StatusState = Literal["works", "attention", "broken", "not_verified", "stale", "unknown", "off"]
StatusSource = Literal["check", "counters", "report", "none"]
Level = Literal["ok", "warn", "fail", "unknown", "off"]


def now_utc() -> datetime:
    """Единые «сейчас» для статусов; тесты подменяют `app.status_model.now_utc`."""
    return datetime.now(UTC)


class StatusFact(BaseModel):
    """Итог для одного места экрана: слово состояния, когда и чем проверено."""

    model_config = ConfigDict(extra="ignore")

    state: StatusState
    checked_at: datetime | None
    source: StatusSource
    live: bool


def legacy_level(state: StatusState) -> Level:
    """Прежний пятиуровневый `status`: «ok» только у «Работает»."""
    mapping: dict[StatusState, Level] = {
        "works": "ok",
        "attention": "warn",
        "broken": "fail",
        "not_verified": "unknown",
        "stale": "unknown",
        "unknown": "unknown",
        "off": "off",
    }
    return mapping[state]


def resolve(
    level: Level,
    *,
    probes: Sequence[datetime | None],
    now: datetime,
    complete: bool = True,
    stale: bool = False,
    source: StatusSource | None = None,
) -> StatusFact:
    """Слово состояния из уровня и проверок.

    `probes` — время живых проверок, на которые опирается карточка (по одной на
    проверяемую часть); `None` — проверка ещё не выполнялась. Пустой список — живой проверки
    у этого факта нет вовсе (счётчики).
    """
    done = [p for p in probes if p is not None]
    live = bool(probes) and len(done) == len(probes)
    default_source: StatusSource = "check" if done else "counters"
    chosen = source or default_source
    if level == "off":
        return StatusFact(state="off", checked_at=None, source="none", live=False)
    if level in ("warn", "fail"):
        return StatusFact(
            state="attention" if level == "warn" else "broken",
            checked_at=max(done) if done else None,
            source=chosen,
            live=bool(done),
        )
    oldest = min(done) if done else None
    if not complete or level == "unknown":
        return StatusFact(state="unknown", checked_at=oldest, source=chosen, live=False)
    if not live:
        return StatusFact(state="not_verified", checked_at=oldest, source=chosen, live=False)
    if stale or oldest is None or now - oldest > STALE_AFTER:
        return StatusFact(state="stale", checked_at=oldest, source=chosen, live=False)
    return StatusFact(state="works", checked_at=oldest, source=chosen, live=True)


def none_fact(state: StatusState = "unknown") -> StatusFact:
    return StatusFact(state=state, checked_at=None, source="none", live=False)


def bus_fact(*, dead: int, answered: Sequence[bool], now: datetime) -> StatusFact:
    """Обмен между системами: сводка по доменам. Не ответил хоть один домен — «Не удалось
    проверить», пустая очередь остальных этого не отменяет; недоставленные события —
    сбой при любом ответе."""
    level: Level = "fail" if dead > 0 else "ok"
    return resolve(level, probes=[now], now=now, complete=all(answered))
