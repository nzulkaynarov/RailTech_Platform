"""Проверка SSO-токена CRM (unit, без базы): порядок и границы проверок из sso-token.md «Токен сотрудника для EDS»."""

import time
import warnings
from typing import Any

import jwt
import pytest

from app.security.sso_token import SsoTokenError, verify_sso_token
from tests.conftest import SSO_CURRENT, SSO_PREVIOUS

SECRETS = [SSO_CURRENT, SSO_PREVIOUS]
NOW = 1_792_000_000.0


def make(secret: str = SSO_CURRENT, *, alg: str = "HS256", **claims: Any) -> str:
    payload: dict[str, Any] = {
        "iss": "crm",
        "aud": "eds",
        "sub": "42",
        "email": "a@example.com",
        "name": "A",
        "permissions": ["letters.read"],
        "iat": NOW,
        "exp": NOW + 60,
        "jti": "5c4b6f2e-3b0e-4d4e-9f5a-9c2a6a1f0a11",
    }
    payload.update({k: v for k, v in claims.items() if v is not ...})
    for key, value in claims.items():
        if value is ...:
            payload.pop(key, None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # HS512 с коротким ключом — нарочно: проверяем отказ по алгоритму
        return jwt.encode(payload, secret, algorithm=alg)


def reason(token: str, now: float = NOW) -> str:
    with pytest.raises(SsoTokenError) as info:
        verify_sso_token(token, SECRETS, now=now)
    return info.value.reason


def test_valid_token_yields_claims() -> None:
    claims = verify_sso_token(make(), SECRETS, now=NOW + 1)
    assert (claims.sub, claims.iss, claims.jti) == (42, "crm", "5c4b6f2e-3b0e-4d4e-9f5a-9c2a6a1f0a11")


def test_rotation_accepts_either_secret() -> None:
    assert verify_sso_token(make(SSO_PREVIOUS), SECRETS, now=NOW).sub == 42


@pytest.mark.parametrize(
    "token",
    [
        make("wrong-secret-wrong-secret-wrong-secret-0"),
        make(SSO_CURRENT, alg="HS512"),
    ],
)
def test_signature_failures(token: str) -> None:
    assert reason(token) == "signature"


def test_unsigned_and_garbage_tokens_are_rejected() -> None:
    unsigned = jwt.encode({"aud": "eds", "sub": "1"}, "", algorithm="none")
    assert reason(unsigned) in {"signature", "malformed"}
    assert reason("not-a-jwt-at-all-not-a-jwt") == "malformed"


def test_audience_is_checked_after_signature() -> None:
    assert reason(make(aud="erp")) == "audience"
    assert reason(make(aud=...)) == "audience"
    assert reason(make(aud=["eds"])) == "audience"
    # неверная подпись важнее неверного aud
    assert reason(make("wrong-secret-wrong-secret-wrong-secret-0", aud="erp")) == "signature"


@pytest.mark.parametrize(
    ("offset", "expected"),
    [(0, None), (5, None), (5.5, "expired"), (60, "expired")],
)
def test_expiry_with_five_seconds_leeway(offset: float, expected: str | None) -> None:
    token = make()  # exp = NOW + 60
    now = NOW + 60 + offset
    if expected is None:
        assert verify_sso_token(token, SECRETS, now=now).sub == 42
    else:
        assert reason(token, now) == expected


@pytest.mark.parametrize(
    ("lifetime", "expected"),
    [(60, None), (65, None), (65.5, "lifetime"), (3600, "lifetime"), (-1, "lifetime")],
)
def test_lifetime_is_limited(lifetime: float, expected: str | None) -> None:
    token = make(exp=NOW + lifetime)
    if expected is None:
        assert verify_sso_token(token, SECRETS, now=NOW).sub == 42
    else:
        assert reason(token) == expected


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": ...},
        {"iat": ...},
        {"jti": ...},
        {"jti": ""},
        {"jti": "x" * 129},
        {"jti": 5},
        {"sub": ...},
        {"sub": 42},
        {"sub": "forty-two"},
        {"sub": "-1"},
        {"sub": "１２"},
        {"exp": "soon"},
        {"iat": True},
    ],
)
def test_structural_problems_are_malformed(claims: dict[str, Any]) -> None:
    assert reason(make(**claims)) == "malformed"


@pytest.mark.parametrize("iss", ["erp", "eds", "CRM", ...])
def test_only_crm_may_issue(iss: Any) -> None:
    assert reason(make(iss=iss)) == "issuer"


@pytest.mark.parametrize(("ahead", "expected"), [(0, None), (5, None), (5.5, "lifetime"), (3600, "lifetime")])
def test_iat_in_the_future_is_rejected(ahead: float, expected: str | None) -> None:
    token = make(iat=NOW + ahead, exp=NOW + ahead + 60)
    if expected is None:
        assert verify_sso_token(token, SECRETS, now=NOW).sub == 42
    else:
        assert reason(token) == expected


def test_permissions_in_token_are_ignored() -> None:
    claims = verify_sso_token(make(permissions=["approvals.decide"], role="admin"), SECRETS, now=NOW)
    assert not hasattr(claims, "permissions")


def test_real_clock_token_passes() -> None:
    now = time.time()
    assert verify_sso_token(make(iat=now, exp=now + 60), SECRETS, now=now).sub == 42
