"""Проблемы зоны ответственности считаются по фактам (ЕВ-З): каждое правило — своим кейсом."""

from datetime import date

import pytest

from app.domain.responsibility_zones import ZoneProblem, missing_sections, zone_problems

TODAY = date(2026, 11, 23)
ACCESS = {1: {"eds.payments": "read", "eds.visa.finance": "full"}, 2: {"admin": "full"}}


def run(**over: object) -> list[ZoneProblem]:
    args: dict[str, object] = {
        "is_active": True,
        "sections": ["eds.payments", "eds.visa.finance"],
        "responsible_id": 1,
        "deputy_id": None,
        "valid_to": None,
        "today": TODAY,
        "active_users": {1, 2, 3},
        "access_of": ACCESS,
    }
    args.update(over)
    return zone_problems(**args)  # type: ignore[arg-type]


def codes(problems: list[ZoneProblem]) -> list[str]:
    return [p.code for p in problems]


def test_healthy_zone_has_no_problems() -> None:
    assert run() == []


def test_no_responsible() -> None:
    assert run(responsible_id=None) == [ZoneProblem("no_responsible", "problem")]


def test_responsible_inactive() -> None:
    assert codes(run(responsible_id=9)) == ["responsible_inactive"]


def test_lacking_permissions_is_a_warning_with_sections() -> None:
    assert run(responsible_id=2) == [
        ZoneProblem(
            "responsible_lacks_permissions", "warning", ("eds.payments", "eds.visa.finance")
        )
    ]


def test_zone_without_sections_never_lacks_permissions() -> None:
    assert run(sections=[], responsible_id=2) == []


def test_deputy_inactive() -> None:
    assert codes(run(deputy_id=9)) == ["deputy_inactive"]
    assert run(deputy_id=3) == []


@pytest.mark.parametrize(
    ("valid_to", "expired"),
    [(date(2026, 11, 22), True), (TODAY, False), (None, False)],
)
def test_term_expired_from_the_date(valid_to: date | None, expired: bool) -> None:
    assert (codes(run(valid_to=valid_to)) == ["term_expired"]) is expired


def test_inactive_zone_reports_nothing() -> None:
    assert run(is_active=False, responsible_id=None, valid_to=date(2020, 1, 1)) == []


def test_missing_sections_keeps_order() -> None:
    assert missing_sections(["b", "a", "c"], {"a": "read"}) == ("b", "c")
