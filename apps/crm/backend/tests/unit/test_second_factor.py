"""ДВ-4: код приложения (TOTP), резервные коды и токены второго фактора — без базы."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from app.security import second_factor as sf
from app.security.tokens import TokenError

KEY = b"k" * 32
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


def code_at(secret: str, at: datetime) -> str:
    return pyotp.TOTP(secret).at(at)


def test_code_accepted_once_and_with_one_step_drift() -> None:
    secret = sf.new_secret()
    step = sf.accept_code(secret, code_at(secret, NOW), None, NOW)
    assert step is not None
    assert sf.accept_code(secret, code_at(secret, NOW), step, NOW) is None  # повтор не проходит
    earlier = sf.accept_code(secret, code_at(secret, NOW - timedelta(seconds=30)), None, NOW)
    assert earlier == step - 1
    assert sf.accept_code(secret, code_at(secret, NOW - timedelta(minutes=2)), None, NOW) is None
    assert sf.accept_code(secret, "12345", None, NOW) is None


def test_backup_codes_are_single_use_and_case_insensitive() -> None:
    codes, hashes = sf.new_backup_codes()
    assert len(codes) == 8
    assert all(len(code) == 9 and code[4] == "-" for code in codes)
    left = sf.consume_backup_code(hashes, codes[0].lower().replace("-", " "))
    assert left is not None
    assert len(left) == 7
    assert sf.consume_backup_code(left, codes[0]) is None


def test_challenge_and_device_tokens_are_not_interchangeable() -> None:
    claims = sf.FactorClaims(7, 100, 200)
    challenge = sf.issue_challenge(KEY, claims, datetime.now(UTC))
    device = sf.issue_device(KEY, claims, datetime.now(UTC))
    assert sf.decode_challenge(KEY, challenge).user_id == 7
    assert sf.decode_device(KEY, device) == claims
    with pytest.raises(TokenError):
        sf.decode_device(KEY, challenge)
    with pytest.raises(TokenError):
        sf.decode_challenge(KEY, device)


def test_challenge_expires_after_five_minutes() -> None:
    old = sf.issue_challenge(KEY, sf.FactorClaims(1, 0), datetime.now(UTC) - timedelta(minutes=6))
    with pytest.raises(TokenError):
        sf.decode_challenge(KEY, old)


def test_otpauth_uri_names_issuer_and_account() -> None:
    uri = sf.otpauth_uri("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP", "a@railtech.uz", "RailTech")
    assert uri.startswith("otpauth://totp/RailTech:a%40railtech.uz?")
    assert "issuer=RailTech" in uri
