"""Дашборд: прошлый период, склейка менеджеров, доля SLA, ряд сделок по дням (SPEC §10.1)."""

from datetime import date, timedelta
from typing import Any

import pytest

from app.schemas.admin import DailyStat
from app.services.dashboard import merge_managers, sla_stat, split_period
from app.services.deals import fill_days


def _day(day: date, leads: int = 1) -> DailyStat:
    return DailyStat(
        day=day,
        leads_created=leads,
        escalations=0,
        taken=0,
        won=0,
        lost=0,
        bot_answers=0,
        fallbacks=0,
        avg_take_minutes=None,
        cost_usd=0.0,
    )


def test_split_period_separates_previous_days() -> None:
    since = date(2026, 10, 6)
    rows = [_day(since + timedelta(days=i)) for i in range(-7, 7)]
    current, before = split_period(rows, since)
    assert [d.day for d in current] == [since + timedelta(days=i) for i in range(7)]
    assert all(d.day < since for d in before)
    assert len(current) + len(before) == len(rows)


@pytest.mark.parametrize(
    ("due", "met", "share"),
    [(0, 0, None), (4, 3, 0.75), (3, 0, 0.0), (3, 3, 1.0), (3, 1, 0.3333)],
)
def test_sla_share(due: int, met: int, share: float | None) -> None:
    stat = sla_stat(due, met)
    assert (stat.due, stat.met, stat.share) == (due, met, share)


def _rows(**kw: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {"taken": [], "won": [], "active": [], "names": [], **kw}


def test_merge_managers_joins_slices_and_sorts() -> None:
    rows = _rows(
        taken=[
            {"user_id": 1, "taken": 2, "median_min": 4.26},
            {"user_id": 2, "taken": 5, "median_min": None},
        ],
        won=[{"user_id": 1, "won": 3}, {"user_id": 3, "won": 1}],
        active=[{"user_id": 3, "active": 7}],
        names=[{"id": 1, "full_name": "Анна"}, {"id": 2, "full_name": "Борис"}],
    )
    out = merge_managers(rows)
    assert [m.user_id for m in out] == [2, 1, 3]
    anna = out[1]
    assert (anna.taken, anna.median_take_minutes, anna.won, anna.active_leads) == (2, 4.3, 3, 0)
    assert out[2].name == "#3"  # пользователь удалён — строка не теряется
    assert (out[2].taken, out[2].median_take_minutes, out[2].active_leads) == (0, None, 7)


def test_merge_managers_empty() -> None:
    assert merge_managers(_rows()) == []


def test_fill_days_has_no_gaps() -> None:
    first, last = date(2026, 10, 1), date(2026, 10, 4)
    out = fill_days({(date(2026, 10, 2), "won"): 2, (date(2026, 10, 4), "lost"): 1}, first, last)
    assert [(d.day.day, d.won, d.lost) for d in out] == [(1, 0, 0), (2, 2, 0), (3, 0, 0), (4, 0, 1)]
