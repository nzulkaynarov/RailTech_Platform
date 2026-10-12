"""Перезапуск SLA-таймера при повышении приоритета и по окончании «Отложить» (аудит P1-8)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.domain.business_hours import BusinessHours
from app.domain.escalation import priority_raised, reset_sla
from app.domain.triggers import Priority

H = BusinessHours()
TZ = ZoneInfo("Asia/Tashkent")


@pytest.mark.parametrize(
    ("now", "minutes", "due"),
    [
        # рабочее время: срок через 30 рабочих минут
        (datetime(2026, 10, 12, 10, 0, tzinfo=TZ), 30, datetime(2026, 10, 12, 10, 30, tzinfo=TZ)),
        # пятница вечером: срок переносится на понедельник
        (datetime(2026, 10, 16, 19, 0, tzinfo=TZ), 15, datetime(2026, 10, 19, 9, 15, tzinfo=TZ)),
    ],
)
def test_reset_sla(now: datetime, minutes: int, due: datetime) -> None:
    timer = reset_sla(now, minutes, H)
    assert timer.sla_due_at == due
    assert timer.sla_notified_at is None


@pytest.mark.parametrize(
    ("before", "after", "raised"),
    [
        (Priority.INFO, Priority.WARM, True),
        (Priority.INFO, Priority.HOT, True),
        (Priority.WARM, Priority.HOT, True),
        (Priority.HOT, Priority.HOT, False),
        (Priority.WARM, Priority.WARM, False),
        (Priority.INFO, Priority.INFO, False),
    ],
)
def test_priority_raised(before: Priority, after: Priority, raised: bool) -> None:
    assert priority_raised(before, after) is raised
