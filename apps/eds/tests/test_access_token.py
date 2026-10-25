"""Токен доступа EDS (unit): выпуск, проверка, срок, чужой секрет, чужие claims."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.security.access_token import (
    AccessTokenError,
    issue_access_token,
    verify_access_token,
)
from tests.conftest import ACCESS_SECRET


def test_roundtrip_and_claims() -> None:
    token = issue_access_token(42, ACCESS_SECRET)
    claims = verify_access_token(token, ACCESS_SECRET)
    assert claims.crm_user_id == 42
    payload = jwt.decode(token, ACCESS_SECRET, algorithms=["HS256"], audience="eds-api")
    assert (payload["iss"], payload["aud"], payload["exp"] - payload["iat"]) == ("eds", "eds-api", 900)
    assert "permissions" not in payload  # права берутся из проекции на момент запроса


def test_expired_token() -> None:
    token = issue_access_token(1, ACCESS_SECRET, now=datetime.now(UTC) - timedelta(minutes=16))
    with pytest.raises(AccessTokenError) as info:
        verify_access_token(token, ACCESS_SECRET)
    assert info.value.reason == "expired"


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        (issue_access_token(1, "other-secret-other-secret-other-secret-1"), "signature"),
        ("garbage", "malformed"),
        (jwt.encode({"sub": "1"}, ACCESS_SECRET, algorithm="HS256"), "malformed"),
        (
            jwt.encode(
                {"iss": "eds", "aud": "eds", "sub": "1", "iat": 1, "exp": 4_000_000_000, "jti": "j"},
                ACCESS_SECRET,
                algorithm="HS256",
            ),
            "malformed",
        ),
        (
            jwt.encode(
                {"iss": "eds", "aud": "eds-api", "sub": "abc", "iat": 1, "exp": 4_000_000_000, "jti": "j"},
                ACCESS_SECRET,
                algorithm="HS256",
            ),
            "malformed",
        ),
    ],
)
def test_rejected_tokens(token: str, reason: str) -> None:
    with pytest.raises(AccessTokenError) as info:
        verify_access_token(token, ACCESS_SECRET)
    assert info.value.reason == reason
