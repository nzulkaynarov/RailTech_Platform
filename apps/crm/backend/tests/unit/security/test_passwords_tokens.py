from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.security.passwords import (
    WeakPasswordError,
    hash_password,
    temporary_password,
    validate_new_password,
    verify_password,
)
from app.security.tokens import AccessClaims, TokenError, decode_access, issue_access

KEY = b"k" * 32
CLAIMS = AccessClaims(user_id=7, roles=("manager",), must_change_password=False)


def test_hash_and_verify() -> None:
    hashed = hash_password("correct horse 42")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse 42")
    assert not verify_password(hashed, "wrong")
    assert not verify_password("not-a-hash", "x")


def test_temporary_password_is_strong_and_random() -> None:
    first, second = temporary_password(), temporary_password()
    assert first != second
    validate_new_password(first, email="ivanov@railtech.uz")


@pytest.mark.parametrize("password", ["short1", "onlyletterslong", "1234567890123", "ivanov12345"])
def test_weak_passwords_rejected(password: str) -> None:
    with pytest.raises(WeakPasswordError):
        validate_new_password(password, email="ivanov@railtech.uz")


def test_access_token_roundtrip() -> None:
    decoded = decode_access(KEY, issue_access(KEY, CLAIMS, 900))
    assert decoded.issued_at is not None
    assert replace(decoded, issued_at=None) == CLAIMS


@pytest.mark.parametrize(
    ("token_key", "issued_ago_s"),
    [(b"x" * 32, 0), (KEY, 1000)],
    ids=["foreign-key", "expired"],
)
def test_invalid_access_tokens(token_key: bytes, issued_ago_s: int) -> None:
    issued = datetime.now(UTC) - timedelta(seconds=issued_ago_s)
    token = issue_access(token_key, CLAIMS, 900, now=issued)
    with pytest.raises(TokenError):
        decode_access(KEY, token)


def test_short_key_refused() -> None:
    with pytest.raises(TokenError):
        issue_access(b"short", CLAIMS, 900)


def test_token_issued_before_a_password_reset_is_closed() -> None:
    from app.security.tokens import closed_by_password_reset

    changed = datetime(2026, 10, 28, 10, 0, 0, 700_000, tzinfo=UTC)
    second = changed.replace(microsecond=0)
    assert closed_by_password_reset(second - timedelta(seconds=1), changed)
    assert not closed_by_password_reset(second, changed)  # выпущен в ту же секунду — после сброса
    assert not closed_by_password_reset(second + timedelta(seconds=5), changed)
    assert not closed_by_password_reset(second, None)  # сброса не было
    assert not closed_by_password_reset(None, changed)


def test_decoded_token_carries_its_issue_time() -> None:
    key = b"k" * 32
    now = datetime.now(UTC) - timedelta(seconds=30)
    claims = decode_access(key, issue_access(key, CLAIMS, 900, now))
    assert claims.issued_at == now.replace(microsecond=0)
