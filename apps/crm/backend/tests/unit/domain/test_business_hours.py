from datetime import UTC, date, datetime, time

import pytest

from app.domain.business_hours import (
    BusinessHours,
    add_business_minutes,
    is_business_time,
    next_business_start,
)

H = BusinessHours()
TZ = H.tz


def tash(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


# 2026-10-05 — понедельник, 2026-10-09 — пятница, 2026-10-10 — суббота.
@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (tash(2026, 10, 5, 9, 0), True),
        (tash(2026, 10, 5, 8, 59), False),
        (tash(2026, 10, 5, 17, 59), True),
        (tash(2026, 10, 5, 18, 0), False),
        (tash(2026, 10, 10, 12), False),
        (datetime(2026, 10, 5, 4, 0, tzinfo=UTC), True),
    ],
)
def test_is_business_time(moment: datetime, expected: bool) -> None:
    assert is_business_time(moment, H) is expected


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (tash(2026, 10, 5, 10), tash(2026, 10, 5, 10)),
        (tash(2026, 10, 5, 7), tash(2026, 10, 5, 9)),
        (tash(2026, 10, 5, 19), tash(2026, 10, 6, 9)),
        (tash(2026, 10, 9, 18), tash(2026, 10, 12, 9)),
        (tash(2026, 10, 10, 12), tash(2026, 10, 12, 9)),
    ],
)
def test_next_business_start(moment: datetime, expected: datetime) -> None:
    assert next_business_start(moment, H) == expected


@pytest.mark.parametrize(
    ("moment", "minutes", "expected"),
    [
        (tash(2026, 10, 5, 10), 15, tash(2026, 10, 5, 10, 15)),
        (tash(2026, 10, 5, 17, 50), 15, tash(2026, 10, 6, 9, 5)),
        (tash(2026, 10, 9, 17, 55), 15, tash(2026, 10, 12, 9, 10)),
        (tash(2026, 10, 10, 12), 15, tash(2026, 10, 12, 9, 15)),
        (tash(2026, 10, 5, 10), 0, tash(2026, 10, 5, 10)),
        (tash(2026, 10, 5, 9), 9 * 60, tash(2026, 10, 5, 18)),
        (tash(2026, 10, 5, 9), 9 * 60 + 1, tash(2026, 10, 6, 9, 1)),
    ],
)
def test_add_business_minutes(moment: datetime, minutes: int, expected: datetime) -> None:
    assert add_business_minutes(moment, minutes, H) == expected


def test_holiday_is_skipped() -> None:
    hours = BusinessHours(holidays=frozenset({date(2026, 10, 6)}))
    assert next_business_start(tash(2026, 10, 5, 19), hours) == tash(2026, 10, 7, 9)


def test_custom_hours() -> None:
    hours = BusinessHours(start=time(10), end=time(12), weekdays=frozenset({5}))
    assert is_business_time(tash(2026, 10, 10, 11), hours)


@pytest.mark.parametrize("fn", [is_business_time, next_business_start])
def test_naive_datetime_rejected(fn: object) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        fn(datetime(2026, 10, 5, 10), H)  # type: ignore[operator]


def test_negative_minutes_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        add_business_minutes(tash(2026, 10, 5, 10), -1, H)
