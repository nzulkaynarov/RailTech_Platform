"""Политики доставки: расписание повторов с jitter, классификация ответов (L3), предохранитель."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum


class Verdict(StrEnum):
    DELIVERED = "delivered"
    RETRY = "retry"
    DEAD = "dead"


#: Ответы, при которых повтор не поможет: сразу `dead` («повторить» из журнала доступно).
PERMANENT_STATUSES = frozenset({400, 404, 410, 413, 415, 422})
#: Ответы, для которых учитывается `Retry-After`.
RETRY_AFTER_STATUSES = frozenset({429, 503})


def classify_status(status_code: int) -> Verdict:
    if 200 <= status_code < 300:
        return Verdict.DELIVERED
    if status_code in PERMANENT_STATUSES:
        return Verdict.DEAD
    return Verdict.RETRY


def parse_retry_after(value: str | None, now: datetime) -> float | None:
    """Секунды из `Retry-After` (число секунд или HTTP-дата); нет или не читается — `None`."""
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return float(raw)
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return None
    return max((moment - now).total_seconds(), 0.0)


@dataclass(frozen=True)
class RetryPolicy:
    """Повторы: 30 с, 2 мин, 10 мин, 1 ч, 6 ч, 24 ч (± `jitter`); неудача после шестого повтора — `dead`.

    `attempts` — сколько попыток уже сделано (первая — не повтор). `Retry-After` ответа 429/503 не сжигает попытки:
    задержка — не меньше шага расписания и не меньше `Retry-After` (не больше `max_retry_after`), плюс jitter вверх,
    чтобы не прийти раньше, чем просил подписчик.
    """

    delays: tuple[float, ...] = (30.0, 120.0, 600.0, 3600.0, 21600.0, 86400.0)
    jitter: float = 0.2
    min_retry_after: float = 1.0
    max_retry_after: float = 86400.0

    @property
    def max_attempts(self) -> int:
        return len(self.delays) + 1

    def delay_after(self, attempts: int, rng: random.Random, retry_after: float | None = None) -> float | None:
        """Через сколько секунд следующая попытка после неудачной попытки № `attempts`; `None` — попытки кончились."""
        if attempts < 1 or attempts > len(self.delays):
            return None
        base = self.delays[attempts - 1]
        asked = None if retry_after is None else min(max(retry_after, self.min_retry_after), self.max_retry_after)
        if asked is not None and asked >= base * (1.0 - self.jitter):
            return max(asked, base) * rng.uniform(1.0, 1.0 + self.jitter)
        return base * rng.uniform(1.0 - self.jitter, 1.0 + self.jitter)


@dataclass(frozen=True)
class BreakerPolicy:
    """Предохранитель подписчика: `threshold` ошибок подряд → пауза `pause_seconds`, затем одна пробная доставка."""

    threshold: int = 5
    pause_seconds: float = 300.0
