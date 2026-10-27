"""Сброс пароля по ссылке: токен, срок, лимит и канал (W15-H6)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import password_reset as pr

NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)


def test_token_hash_roundtrip() -> None:
    token = pr.new_token()
    assert len(token) >= 40
    assert token not in pr.hash_token(token)
    assert pr.same_token(token, pr.hash_token(token))
    assert not pr.same_token(pr.new_token(), pr.hash_token(token))


@pytest.mark.parametrize(
    ("mail", "tg", "expected"),
    [
        (True, True, "email"),
        (True, False, "email"),
        (False, True, "telegram"),
        (False, False, None),
    ],
)
def test_delivery_channel(mail: bool, tg: bool, expected: str | None) -> None:
    assert pr.delivery_channel(mail_ready=mail, telegram_ready=tg) == expected


@pytest.mark.parametrize(("count", "blocked"), [(0, False), (2, False), (3, True), (10, True)])
def test_rate(count: int, blocked: bool) -> None:
    assert pr.rate_exceeded(count) is blocked


def test_usable_requires_unused_and_unexpired() -> None:
    soon = NOW + pr.TOKEN_TTL
    assert pr.usable(soon, None, NOW)
    assert not pr.usable(soon, NOW, NOW)  # уже использован
    assert not pr.usable(soon, None, soon)  # срок вышел
    assert not pr.usable(NOW - timedelta(seconds=1), None, NOW)


def test_reset_link() -> None:
    assert pr.reset_link("https://platform.example.com/", "tok") == (
        "https://platform.example.com/reset-password?token=tok"
    )
