"""Антиспам формы «Запрос» (M3-CRM-05): токен формы, honeypot, окно запросов по IP."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.web_form import (
    SlidingWindowLimiter,
    TokenVerdict,
    check_form_token,
    is_honeypot_filled,
    issue_form_token,
)

KEY = b"unit-test-form-key"
OTHER_KEY = b"another-key"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _check(token: str | None, now: datetime, key: bytes = KEY) -> TokenVerdict:
    return check_form_token(key, token, now, min_fill_s=3, ttl_s=3600)


@pytest.mark.parametrize(
    ("elapsed_s", "expected"),
    [
        (0, TokenVerdict.TOO_FAST),
        (2, TokenVerdict.TOO_FAST),
        (3, TokenVerdict.OK),
        (60, TokenVerdict.OK),
        (3600, TokenVerdict.OK),
        (3601, TokenVerdict.EXPIRED),
        (-5, TokenVerdict.TOO_FAST),
    ],
)
def test_token_timing(elapsed_s: int, expected: TokenVerdict) -> None:
    token = issue_form_token(KEY, NOW)
    assert _check(token, NOW + timedelta(seconds=elapsed_s)) == expected


@pytest.mark.parametrize(
    "token",
    [None, "", "garbage", "1760356800", "1760356800.", "abc.def", "1760356800.0000", ".sig"],
)
def test_malformed_tokens_are_invalid(token: str | None) -> None:
    assert _check(token, NOW) == TokenVerdict.INVALID


def test_token_signed_with_another_key_or_tampered_is_invalid() -> None:
    token = issue_form_token(KEY, NOW)
    assert _check(token, NOW + timedelta(seconds=10), key=OTHER_KEY) == TokenVerdict.INVALID
    issued, _, signature = token.partition(".")
    forged = f"{int(issued) - 600}.{signature}"
    assert _check(forged, NOW + timedelta(seconds=10)) == TokenVerdict.INVALID


def test_token_is_stable_for_the_same_second() -> None:
    assert issue_form_token(KEY, NOW) == issue_form_token(KEY, NOW + timedelta(milliseconds=500))


@pytest.mark.parametrize(
    ("value", "filled"),
    [(None, False), ("", False), ("  ", False), ("http://spam", True), ("x", True)],
)
def test_honeypot(value: str | None, filled: bool) -> None:
    assert is_honeypot_filled(value) is filled


def test_limiter_sliding_window_per_key() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_s=60)
    assert limiter.allow("1.1.1.1", NOW)
    assert limiter.allow("1.1.1.1", NOW + timedelta(seconds=10))
    assert not limiter.allow("1.1.1.1", NOW + timedelta(seconds=20))
    # Другой ключ — своё окно.
    assert limiter.allow("2.2.2.2", NOW + timedelta(seconds=20))
    # Первое обращение вышло из окна — снова можно.
    assert limiter.allow("1.1.1.1", NOW + timedelta(seconds=60))
    assert not limiter.allow("1.1.1.1", NOW + timedelta(seconds=61))


def test_limiter_forgets_stale_keys() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_s=10)
    limiter.allow("a", NOW)
    limiter.allow("b", NOW + timedelta(seconds=9))
    limiter.forget_stale(NOW + timedelta(seconds=10))
    assert limiter.allow("a", NOW + timedelta(seconds=10))
    assert not limiter.allow("b", NOW + timedelta(seconds=10))
