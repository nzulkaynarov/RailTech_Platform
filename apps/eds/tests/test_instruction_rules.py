"""Правила пути делопроизводства без базы (P8b, бенчмарк СЭД §6.4): путь резолюции, рабочие дни, подсказка срока,
расписание напоминаний. Время — аргумент, часы не нужны."""

from datetime import UTC, date, datetime

import pytest

from app.models import Letter
from app.schemas.letters import LetterTrack
from app.services.instructions import next_workday, prev_workday, reminder_due, suggested_due, track_of

MON, FRI, SAT, SUN = date(2026, 11, 2), date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 8)


def letter(**values: object) -> Letter:
    base: dict[str, object] = {
        "doc_kind": "government",
        "erp_request_id": None,
        "erp_deal_id": None,
        "urgent": False,
        "document_due": None,
        "registered_at": datetime(2026, 11, 2, 5, 0, tzinfo=UTC),  # пн, 10:00 Ташкент
    }
    return Letter(**{**base, **values})


@pytest.mark.parametrize(
    ("values", "track"),
    [
        ({"erp_request_id": 905, "erp_deal_id": 905, "doc_kind": None}, LetterTrack.CALC),  # «Создать заявку»
        ({"erp_request_id": 905, "doc_kind": "counterparty"}, LetterTrack.CALC),  # связь с заявкой — путь заявки
        ({"erp_deal_id": 905, "doc_kind": None}, LetterTrack.CALC),  # старое событие без заявки, письма до P8
        ({"erp_deal_id": 905, "doc_kind": "supplier"}, LetterTrack.OFFICE),  # сделка — контекст делопроизводства
        ({"doc_kind": "tax_notice"}, LetterTrack.OFFICE),
        ({"doc_kind": None}, LetterTrack.OFFICE),  # без связей и вида — не заявка
    ],
)
def test_track_rule(values: dict[str, object], track: LetterTrack) -> None:
    assert track_of(letter(**values)) is track


def test_workdays_skip_the_weekend() -> None:
    assert next_workday(SAT) == date(2026, 11, 9)
    assert next_workday(FRI) == FRI
    assert prev_workday(MON) == date(2026, 10, 30)  # пятница
    assert prev_workday(date(2026, 11, 3)) == MON


def test_suggested_due_from_document_due_minus_a_workday() -> None:
    assert suggested_due(letter(document_due=date(2026, 11, 9)), MON) == FRI  # пн → пт
    assert suggested_due(letter(document_due=date(2026, 11, 5)), MON) == date(2026, 11, 4)


def test_suggested_due_without_document_due_is_3_or_10_days_shifted_to_a_workday() -> None:
    assert suggested_due(letter(), MON) == date(2026, 11, 12)  # +10 дней — чт
    assert suggested_due(letter(urgent=True), MON) == date(2026, 11, 5)  # +3 дня
    wednesday = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    assert suggested_due(letter(registered_at=wednesday, urgent=True), MON) == date(2026, 11, 9)  # ср + 3 = сб → пн
    assert suggested_due(letter(registered_at=wednesday), MON) == date(2026, 11, 16)  # ср + 10 = сб → пн


def test_suggested_due_is_never_in_the_past_and_none_for_calc() -> None:
    assert suggested_due(letter(document_due=date(2026, 10, 20)), MON) == MON
    assert suggested_due(letter(erp_request_id=1, doc_kind=None), MON) is None


def test_reminders_short_term_one_workday_before_and_on_the_day() -> None:
    issued, due = MON, FRI
    assert reminder_due(due, issued, MON, []) is None
    assert reminder_due(due, issued, date(2026, 11, 5), []) == "d1"  # чт
    assert reminder_due(due, issued, date(2026, 11, 5), ["d1"]) is None
    assert reminder_due(due, issued, FRI, ["d1"]) == "d0"
    assert reminder_due(due, issued, FRI, ["d1", "d0"]) is None
    assert reminder_due(due, issued, SAT, ["d1", "d0"]) == "overdue"
    assert reminder_due(due, issued, date(2026, 11, 10), ["d1", "d0", "overdue"]) is None


def test_reminders_long_term_add_three_days_before_and_monday_due_reminds_on_friday() -> None:
    issued, due = date(2026, 10, 26), date(2026, 11, 9)  # 14 дней, срок — понедельник
    assert reminder_due(due, issued, date(2026, 11, 5), []) is None
    assert reminder_due(due, issued, FRI, []) == "d1"  # за 3 дня — пт (сб → пт) и за рабочий день — пт: одно
    assert reminder_due(due, issued, SAT, ["d3", "d1"]) is None
    assert reminder_due(due, issued, date(2026, 11, 9), ["d3", "d1"]) == "d0"
    wednesday = date(2026, 11, 11)
    assert reminder_due(wednesday, issued, date(2026, 11, 8), []) == "d3"  # 11.11 − 3 = вс 08.11 → пт 06.11
    assert reminder_due(wednesday, issued, date(2026, 11, 10), ["d3"]) == "d1"


def test_reminders_short_term_has_no_three_day_point_and_missed_points_collapse() -> None:
    issued, due = MON, date(2026, 11, 12)  # 10 дней — не больше 10: без «за 3 дня»
    assert reminder_due(due, issued, date(2026, 11, 9), []) is None
    # Воркер стоял: в день срока уходит одно «сегодня», не три подряд.
    assert reminder_due(due, issued, due, []) == "d0"


def test_due_on_issue_day_does_not_repeat_the_assignment_notice() -> None:
    assert reminder_due(MON, MON, MON, []) is None
    assert reminder_due(MON, MON, date(2026, 11, 3), []) == "overdue"
