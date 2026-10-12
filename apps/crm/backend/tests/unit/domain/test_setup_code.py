"""Одноразовый код мастера первого запуска: формат, срок, перебор, гашение."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.errors import Reason, ValidationFailedError
from app.domain.setup_code import CODE_LENGTH, SetupCodeGate, new_code, normalize

T0 = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def _reason(gate: SetupCodeGate, code: str, now: datetime) -> str | None:
    try:
        gate.verify(code, now)
    except ValidationFailedError as exc:
        return str(exc.details["reason"])
    return None


def test_code_is_long_and_random() -> None:
    codes = {new_code() for _ in range(50)}
    assert len(codes) == 50
    assert all(len(c) == CODE_LENGTH >= 12 for c in codes)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("abcd-efgh 2345", "ABCDEFGH2345"), (" ABCD ", "ABCD"), ("", "")],
)
def test_normalize(typed: str, expected: str) -> None:
    assert normalize(typed) == expected


@pytest.mark.parametrize(
    ("offset", "use_right_code", "reason"),
    [
        (timedelta(0), True, None),
        (timedelta(hours=23, minutes=59), True, None),
        (timedelta(hours=24), True, Reason.SETUP_CODE_EXPIRED),
        (timedelta(0), False, Reason.SETUP_CODE_INVALID),
        (timedelta(hours=30), False, Reason.SETUP_CODE_INVALID),
    ],
)
def test_verify(offset: timedelta, use_right_code: bool, reason: Reason | None) -> None:
    gate = SetupCodeGate()
    code = gate.issue(T0)
    typed = code if use_right_code else "WRONG" + code[5:][::-1] + "X"
    assert _reason(gate, typed, T0 + offset) == (reason.value if reason else None)


def test_lowercase_and_dashes_accepted() -> None:
    gate = SetupCodeGate()
    code = gate.issue(T0)
    assert _reason(gate, f"{code[:4].lower()}-{code[4:]}", T0) is None


def test_lockout_after_too_many_failures() -> None:
    gate = SetupCodeGate(max_failures=3)
    code = gate.issue(T0)
    for _ in range(3):
        assert _reason(gate, "BAD", T0) == Reason.SETUP_CODE_INVALID.value
    assert _reason(gate, code, T0) == Reason.SETUP_LOCKED.value
    assert _reason(gate, code, T0 + gate.lockout) is None


def test_consumed_code_no_longer_works() -> None:
    gate = SetupCodeGate()
    code = gate.issue(T0)
    gate.consume()
    assert not gate.is_valid(T0)
    assert _reason(gate, code, T0) == Reason.SETUP_CODE_EXPIRED.value
