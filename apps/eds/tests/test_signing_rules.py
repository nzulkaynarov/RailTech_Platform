"""Инварианты основания полномочия подписи без базы (ADR-0024 п. 1; ГК РУз ст. 139)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.services import signing_rules as rules

D = date


def poa(**changes: object) -> rules.Terms:
    base = rules.Terms(
        kinds=("letter_out",),
        basis="power_of_attorney",
        basis_number="17",
        basis_date=D(2026, 3, 1),
        valid_from=D(2026, 3, 1),
        valid_to=D(2027, 3, 1),
        limit_amount=None,
        limit_currency=None,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def charter(**changes: object) -> rules.Terms:
    base = rules.Terms(
        kinds=("letter_out", "contract"),
        basis="charter",
        basis_number=None,
        basis_date=None,
        valid_from=D(2026, 1, 1),
        valid_to=None,
        limit_amount=None,
        limit_currency=None,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_valid_power_of_attorney_and_charter_pass() -> None:
    assert rules.check(poa()) == {}
    assert rules.check(charter()) == {}


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"basis_number": None}, "basis_number"),
        ({"basis_number": ""}, "basis_number"),
        ({"basis_date": None}, "basis_date"),
        ({"valid_to": None}, "valid_to"),
    ],
)
def test_power_of_attorney_requires_number_date_and_term(changes: dict[str, object], field: str) -> None:
    assert field in rules.check(poa(**changes))


def test_power_of_attorney_term_is_at_most_three_years_from_issue_date() -> None:
    assert rules.check(poa(valid_to=D(2029, 3, 1))) == {}
    problems = rules.check(poa(valid_to=D(2029, 3, 2)))
    assert set(problems) == {"valid_to"}
    assert "01.03.2029" in problems["valid_to"]


def test_leap_day_issue_date_ends_on_february_28() -> None:
    assert rules.power_of_attorney_deadline(D(2024, 2, 29)) == D(2027, 2, 28)
    assert rules.check(poa(basis_date=D(2024, 2, 29), valid_from=D(2024, 2, 29), valid_to=D(2027, 2, 28))) == {}
    assert "valid_to" in rules.check(poa(basis_date=D(2024, 2, 29), valid_from=D(2024, 2, 29), valid_to=D(2027, 3, 1)))


def test_power_of_attorney_cannot_start_before_issue_date() -> None:
    assert "valid_from" in rules.check(poa(valid_from=D(2026, 2, 28)))


def test_charter_has_no_number_but_may_have_no_end() -> None:
    assert "basis_number" in rules.check(charter(basis_number="1"))
    assert rules.check(charter(valid_to=D(2030, 1, 1))) == {}


def test_order_needs_number_and_date_but_no_term() -> None:
    order = charter(basis="order", basis_number="12-к", basis_date=D(2026, 5, 4))
    assert rules.check(order) == {}
    assert set(rules.check(replace(order, basis_number=None, basis_date=None))) == {"basis_number", "basis_date"}


def test_limit_is_amount_and_currency_together_and_positive() -> None:
    assert rules.check(charter(limit_amount=Decimal("1000000.00"), limit_currency="UZS")) == {}
    assert "limit_currency" in rules.check(charter(limit_amount=Decimal("5.00")))
    assert "limit_amount" in rules.check(charter(limit_currency="UZS"))
    assert "limit_amount" in rules.check(charter(limit_amount=Decimal("0.00"), limit_currency="UZS"))


def test_period_kinds_and_basis_are_checked() -> None:
    assert "valid_to" in rules.check(charter(valid_to=D(2025, 12, 31)))
    assert "kinds" in rules.check(charter(kinds=()))
    assert "kinds" in rules.check(charter(kinds=("act", "act")))
    assert "basis" in rules.check(charter(basis="verbal"))


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://vakolat.uz/ru/proxy/12345", True),
        ("https://www.vakolat.uz/p/1", True),
        ("http://vakolat.uz/p/1", False),
        ("https://vakolat.uz.evil.example/p/1", False),
        ("https://evilvakolat.uz/p/1", False),
        ("javascript:alert(1)", False),
    ],
)
def test_vakolat_link_must_be_https_on_vakolat_domain(url: str, ok: bool) -> None:
    assert rules.is_vakolat_url(url) is ok
    assert (rules.check(poa(vakolat_url=url)) == {}) is ok
