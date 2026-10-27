"""Срок первого ответа на запрос с сайта (D1-9): настройка, рабочие часы, «ждёт» и «просрочен»."""

from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.settings import AppSettings
from app.services import web_lead_sla

# Вторник 2026-10-27 10:00 по Ташкенту (UTC+5) — рабочее время; пятница вечером — нерабочее.
TUE_WORK = datetime(2026, 10, 27, 5, 0, tzinfo=UTC)
FRI_EVENING = datetime(2026, 10, 30, 14, 30, tzinfo=UTC)  # 19:30 Ташкент


def cfg(minutes: int) -> AppSettings:
    settings = AppSettings()
    settings.web_form.first_response_sla_minutes = minutes
    return settings


def test_sla_default_is_a_setting_not_a_constant() -> None:
    assert AppSettings().web_form.first_response_sla_minutes == 15
    assert web_lead_sla.due_at(cfg(15), TUE_WORK) == TUE_WORK + timedelta(minutes=15)
    assert web_lead_sla.due_at(cfg(45), TUE_WORK) == TUE_WORK + timedelta(minutes=45)


def test_due_at_counts_business_minutes_only() -> None:
    """Запрос в пятницу вечером ждёт до понедельника: срок — рабочие минуты, не календарные."""
    due = web_lead_sla.due_at(cfg(15), FRI_EVENING)
    assert due > FRI_EVENING + timedelta(days=2)


def test_settings_bounds_reject_zero_and_a_day_plus() -> None:
    from pydantic import ValidationError

    from app.schemas.settings import WebFormSettings

    with pytest.raises(ValidationError):
        WebFormSettings(first_response_sla_minutes=0)
    with pytest.raises(ValidationError):
        WebFormSettings(first_response_sla_minutes=1441)


@pytest.mark.parametrize(
    ("due", "assigned", "waiting", "overdue"),
    [
        (None, None, False, False),  # лид другого источника: срока нет
        (TUE_WORK + timedelta(minutes=5), None, True, False),  # срок впереди
        (TUE_WORK - timedelta(minutes=5), None, True, True),  # срок прошёл, никто не взял
        (TUE_WORK - timedelta(minutes=5), 7, False, False),  # взял менеджер — запрос отвечен
        (TUE_WORK, None, True, True),  # ровно в срок — уже просрочен
    ],
)
def test_waiting_and_overdue(
    due: datetime | None, assigned: int | None, waiting: bool, overdue: bool
) -> None:
    assert web_lead_sla.awaiting(due, assigned) is waiting
    assert web_lead_sla.overdue(due, assigned, TUE_WORK) is overdue
