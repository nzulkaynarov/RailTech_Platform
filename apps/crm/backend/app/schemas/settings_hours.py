"""Рабочие часы в настройках (`business_hours`) и их описание словами для текстов бота.

Вынесено из `settings.py` (лимит размера файла). Узбекский — латиница oʻ/gʻ.
"""

from datetime import date, datetime, time
from typing import Final

from pydantic import Field

from app.domain.business_hours import BusinessHours, next_business_start
from app.schemas.settings_base import Language, StrictModel

_DAYS: Final[dict[str, tuple[str, ...]]] = {
    "ru": ("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
    "uz": ("dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
# «ответим в понедельник с 9:00» — день недели в нужной форме.
_ON_DAY: Final[dict[str, tuple[str, ...]]] = {
    "ru": (
        "в понедельник",
        "во вторник",
        "в среду",
        "в четверг",
        "в пятницу",
        "в субботу",
        "в воскресенье",
    ),
    "uz": tuple(f"{d} kuni" for d in _DAYS["uz"]),
    "en": (
        "on Monday",
        "on Tuesday",
        "on Wednesday",
        "on Thursday",
        "on Friday",
        "on Saturday",
        "on Sunday",
    ),
}
_TODAY: Final = {
    "ru": ("сегодня", "завтра"),
    "uz": ("bugun", "ertaga"),
    "en": ("today", "tomorrow"),
}
_ZONES: Final[dict[str, dict[str, str]]] = {
    "Asia/Tashkent": {"ru": "по Ташкенту", "uz": "Toshkent vaqti bilan", "en": "Tashkent time"},
}
_WEEK: Final = 7


def _day_ranges(days: list[int], names: tuple[str, ...]) -> str:
    """[0,1,2,3,4] → «пн–пт»; [0,2,4] → «пн, ср, пт»."""
    groups: list[list[int]] = []
    for day in days:
        if groups and day == groups[-1][-1] + 1:
            groups[-1].append(day)
        else:
            groups.append([day])
    parts = [
        f"{names[g[0]]}–{names[g[-1]]}" if len(g) > 2 else ", ".join(names[d] for d in g)
        for g in groups
    ]
    return ", ".join(parts)


def _clock(value: time) -> str:
    return f"{value:%H:%M}".lstrip("0") or "0:00"


class BusinessHoursSettings(StrictModel):
    timezone: str = "Asia/Tashkent"
    start: time = time(9, 0)
    end: time = time(18, 0)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    holidays: list[date] = Field(default_factory=list)

    def describe(self, language: Language) -> str:
        """«пн–пт с 9:00 до 18:00 по Ташкенту» на языке лида — для текстов бота."""
        days = _day_ranges(sorted(set(self.weekdays)), _DAYS[language])
        start, end = _clock(self.start), _clock(self.end)
        place = _ZONES.get(self.timezone, {}).get(language, self.timezone)
        if language == "uz":
            return f"{days}, {place} {start} dan {end} gacha"
        if language == "en":
            return f"{days}, {start}–{end} {place}"
        return f"{days} с {start} до {end} {place}"

    def next_open(self, now: datetime, language: Language) -> str:
        """Когда ответим: «завтра с 9:00», «в понедельник с 9:00» — с учётом праздников."""
        opens = next_business_start(now, self.domain())
        today = now.astimezone(self.domain().tz).date()
        delta = (opens.date() - today).days
        if delta < len(_TODAY[language]):
            day = _TODAY[language][delta]
        elif delta < _WEEK:
            day = _ON_DAY[language][opens.weekday()]
        else:
            day = f"{opens:%d.%m}"
        clock = _clock(self.start)
        if language == "uz":
            return f"{day} soat {clock} dan"
        if language == "en":
            return f"{day} from {clock}"
        return f"{day} с {clock}"

    def domain(self) -> BusinessHours:
        return BusinessHours(
            timezone=self.timezone,
            start=self.start,
            end=self.end,
            weekdays=frozenset(self.weekdays),
            holidays=frozenset(self.holidays),
        )
