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
from app.security.tokens import (
    AccessClaims,
    TokenError,
    decode_access,
    issue_access,
    password_version,
)

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
    assert decode_access(KEY, issue_access(KEY, CLAIMS, 900)) == CLAIMS


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


def test_password_version_is_exact_microseconds_and_zero_without_a_change() -> None:
    changed = datetime(2026, 10, 28, 10, 0, 0, 123_456, tzinfo=UTC)
    assert password_version(None) == 0
    assert password_version(changed) == 1_793_181_600_123_456
    assert password_version(changed) != password_version(changed + timedelta(microseconds=1))


def test_token_carries_the_password_version_it_was_issued_with() -> None:
    claims = replace(CLAIMS, password_version=1_793_181_600_123_456)
    assert (
        decode_access(KEY, issue_access(KEY, claims, 900)).password_version
        == claims.password_version
    )
    # Токен без поля (выпущен до этой правки) — версия 0: совпадает с «пароль не менялся».
    assert decode_access(KEY, issue_access(KEY, CLAIMS, 900)).password_version == 0


def test_refresh_created_before_the_password_change_is_closed() -> None:
    from app.security.tokens import closed_by_password_change

    changed = datetime(2026, 10, 28, 10, 0, 0, tzinfo=UTC)
    assert closed_by_password_change(changed - timedelta(microseconds=1), changed)
    assert not closed_by_password_change(changed, changed)  # выпущен на момент смены
    assert not closed_by_password_change(changed + timedelta(seconds=1), changed)
    assert not closed_by_password_change(changed, None)
