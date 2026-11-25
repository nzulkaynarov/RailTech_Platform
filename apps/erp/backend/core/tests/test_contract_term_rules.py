"""ДС-1: арифметика срока договора — граница декабря, високосный год, продление без дыр (чистые функции, без базы)."""

import datetime as dt

from core.contract_term import ContractTermRule as R
from core.contract_term import first_term, next_term

D = dt.date


def test_signed_before_december_runs_to_the_end_of_the_year():
    term = first_term(D(2026, 11, 30), R.CALENDAR_YEAR, notice_days=30)
    assert (term.valid_until, term.last_notice_date) == (D(2026, 12, 31), D(2026, 12, 1))


def test_signed_on_the_december_boundary_runs_to_the_end_of_next_year():
    term = first_term(D(2026, 12, 1), R.CALENDAR_YEAR, notice_days=30)
    assert (term.valid_until, term.last_notice_date) == (D(2027, 12, 31), D(2027, 12, 1))


def test_boundary_day_is_a_setting():
    assert first_term(D(2026, 12, 14), R.CALENDAR_YEAR, notice_days=10, boundary_day=15).valid_until == D(2026, 12, 31)
    assert first_term(D(2026, 12, 15), R.CALENDAR_YEAR, notice_days=10, boundary_day=15).valid_until == D(2027, 12, 31)


def test_notice_day_is_never_before_signing_even_with_a_late_boundary():
    # граница 31 декабря: подписано 20 декабря — до конца года меньше 30 дней, срок уходит на следующий год
    term = first_term(D(2026, 12, 20), R.CALENDAR_YEAR, notice_days=30, boundary_day=31)
    assert term.valid_until == D(2027, 12, 31) and term.last_notice_date >= D(2026, 12, 20)


def test_twelve_months_from_a_leap_day_ends_before_the_anniversary():
    term = first_term(D(2028, 2, 29), R.TWELVE_MONTHS, notice_days=30)
    assert term.valid_until == D(2029, 2, 27)  # годовщина 29 февраля в невисокосном году — 28 февраля


def test_twelve_months_ordinary_day():
    assert first_term(D(2026, 3, 15), R.TWELVE_MONTHS, notice_days=30).valid_until == D(2027, 3, 14)


def test_open_term_has_no_end_and_no_notice_day():
    term = first_term(D(2026, 5, 1), R.OPEN, notice_days=30)
    assert (term.valid_until, term.last_notice_date) == (None, None)


def test_next_calendar_term_follows_the_previous_one():
    term = next_term(D(2026, 12, 31), R.CALENDAR_YEAR, notice_days=30, today=D(2027, 1, 1))
    assert (term.valid_from, term.valid_until, term.last_notice_date) == (
        D(2027, 1, 1),
        D(2027, 12, 31),
        D(2027, 12, 1),
    )


def test_renewal_after_a_long_pause_closes_every_missed_year_and_is_stable():
    first = next_term(D(2026, 12, 31), R.CALENDAR_YEAR, notice_days=30, today=D(2029, 6, 1))
    assert first.valid_until == D(2029, 12, 31)
    again = next_term(first.valid_until, R.CALENDAR_YEAR, notice_days=30, today=D(2029, 6, 1))
    assert again.valid_from == D(2030, 1, 1)  # вызывают только когда срок вышел; сам результат срок не режет


def test_twelve_month_chain_across_a_leap_year():
    term = next_term(D(2029, 2, 27), R.TWELVE_MONTHS, notice_days=30, today=D(2029, 3, 1))
    assert (term.valid_from, term.valid_until) == (D(2029, 2, 28), D(2030, 2, 27))
