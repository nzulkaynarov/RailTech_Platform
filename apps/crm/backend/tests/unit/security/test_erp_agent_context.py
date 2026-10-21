"""Контекст вызова erp-mcp: формат по `mcp-tools.json` (claims, типы, подпись, срок, jti)."""

import base64
import hashlib
import hmac
import json
import re
from typing import Any

import pytest

from app.security.erp_agent_context import ErpScope, issue_erp_context

KEY = b"unit-test-key-not-a-secret-0123456789"
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def decode(token: str) -> tuple[dict[str, Any], str, str]:
    payload, _, signature = token.partition(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return claims, payload, signature


def test_claims_match_the_contract() -> None:
    scope = ErpScope(crm_client_id=7, erp_company_id=42, language="uz", trace_id="t-1")
    claims, _, _ = decode(issue_erp_context(KEY, scope, now=lambda: 1_000_000.9))
    assert claims == {
        "crm_client_id": 7,
        "erp_company_id": 42,
        "mode": "customer",
        "language": "uz",
        "iat": 1_000_000,
        "exp": 1_000_060,
        "jti": claims["jti"],
        "trace_id": "t-1",
    }
    assert UUID4.match(claims["jti"])
    # Типы строгие: целые числа — JSON-integer, не bool и не строки.
    assert all(type(claims[k]) is int for k in ("crm_client_id", "erp_company_id", "iat", "exp"))


def test_trace_id_is_optional() -> None:
    claims, _, _ = decode(issue_erp_context(KEY, ErpScope(1, 2)))
    assert "trace_id" not in claims


def test_signature_is_hmac_sha256_of_the_payload() -> None:
    _, payload, signature = decode(issue_erp_context(KEY, ErpScope(1, 2)))
    expected = hmac.new(KEY, payload.encode("ascii"), hashlib.sha256).digest()
    assert signature == base64.urlsafe_b64encode(expected).rstrip(b"=").decode("ascii")


def test_every_issue_has_a_fresh_jti() -> None:
    jtis = {decode(issue_erp_context(KEY, ErpScope(1, 2)))[0]["jti"] for _ in range(20)}
    assert len(jtis) == 20


def test_lifetime_fits_the_contract_window() -> None:
    claims, _, _ = decode(issue_erp_context(KEY, ErpScope(1, 2)))
    assert 0 < claims["exp"] - claims["iat"] <= 60


@pytest.mark.parametrize(
    ("key", "scope"),
    [(b"", ErpScope(1, 2)), (KEY, ErpScope(0, 2)), (KEY, ErpScope(1, 0)), (KEY, ErpScope(-1, 2))],
)
def test_refuses_to_issue_without_key_or_identifiers(key: bytes, scope: ErpScope) -> None:
    with pytest.raises(ValueError, match=r"ERP_MCP_CONTEXT_KEY|positive"):
        issue_erp_context(key, scope)
