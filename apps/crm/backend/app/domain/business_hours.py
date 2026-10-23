"""Рабочие часы (CONVENTIONS.md §11: Asia/Tashkent, 09:00–18:00, пн–пт).

Значения — `settings.business_hours`.
"""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class BusinessHours:
    timezone: str = "Asia/Tashkent"
    start: time = time(9, 0)
    end: time = time(18, 0)
    weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    holidays: Collection[date] = field(default_factory=frozenset)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def is_working_day(self, day: date) -> bool:
        return day.weekday() in self.weekdays and day not in self.holidays


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")


def is_business_time(moment: datetime, hours: BusinessHours) -> bool:
    _require_aware(moment)
    local = moment.astimezone(hours.tz)
    return hours.is_working_day(local.date()) and hours.start <= local.time() < hours.end


def next_business_start(moment: datetime, hours: BusinessHours) -> datetime:
    """Ближайший момент рабочего времени ≥ `moment` (сам момент, если он рабочий)."""
    _require_aware(moment)
    if is_business_time(moment, hours):
        return moment
    local = moment.astimezone(hours.tz)
    day = local.date()
    if hours.is_working_day(day) and local.time() < hours.start:
        return datetime.combine(day, hours.start, hours.tz)
    for offset in range(1, 370):
        candidate = day + timedelta(days=offset)
        if hours.is_working_day(candidate):
            return datetime.combine(candidate, hours.start, hours.tz)
    raise ValueError("no working days configured")


def add_business_minutes(moment: datetime, minutes: int, hours: BusinessHours) -> datetime:
    """Срок SLA: `minutes` рабочих минут начиная с `moment` (SPEC §8.2)."""
    if minutes < 0:
        raise ValueError("minutes must be non-negative")
    current = next_business_start(moment, hours)
    remaining = timedelta(minutes=minutes)
    while True:
        local = current.astimezone(hours.tz)
        day_end = datetime.combine(local.date(), hours.end, hours.tz)
        available = day_end - local
        if remaining <= available:
            return local + remaining
        remaining -= available
        current = next_business_start(day_end, hours)
