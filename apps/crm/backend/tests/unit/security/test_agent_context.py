import base64
import json
import uuid

import pytest

from app.security.agent_context import AgentContextError, issue, verify

KEY = b"k" * 32
OTHER_KEY = b"x" * 32
NOW = 1_800_000_000.0


def clock(value: float = NOW) -> float:
    return value


def sign(payload: dict[str, object]) -> str:
    import hashlib
    import hmac

    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(KEY, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig.rstrip(b'=').decode()}"


def make(**overrides: object) -> str:
    params: dict[str, object] = {"lead_id": 7, "mode": "prospect", "language": "ru"}
    params.update(overrides)
    return issue(KEY, now=clock, **params)  # type: ignore[arg-type]


def decode(token: str) -> dict[str, object]:
    payload = token.split(".")[0]
    raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    claims: dict[str, object] = json.loads(raw)
    return claims


def test_roundtrip() -> None:
    context = verify(make(client_id=3, mode="customer"), KEY, now=clock)
    assert (context.lead_id, context.client_id, context.mode) == (7, 3, "customer")
    assert context.exp - context.iat == 60


def test_issued_claims_follow_the_contract_format() -> None:
    """Контракт mcp-tools.json: целые iat/exp (срок ровно 60 с) и одноразовый jti (UUID v4)."""
    claims = decode(make())
    assert claims["iat"] == int(NOW)
    assert claims["exp"] == int(NOW) + 60
    assert type(claims["iat"]) is int
    assert type(claims["exp"]) is int
    jti = claims["jti"]
    assert isinstance(jti, str)
    assert uuid.UUID(jti).version == 4
    assert str(uuid.UUID(jti)) == jti


def test_every_issue_gets_a_fresh_jti() -> None:
    assert decode(make())["jti"] != decode(make())["jti"]


def test_rejects_context_without_jti() -> None:
    payload = {"lead_id": 1, "mode": "prospect", "language": "ru", "iat": NOW, "exp": NOW + 60}
    with pytest.raises(AgentContextError, match="malformed"):
        verify(sign(payload), KEY, now=clock)


def test_rejects_non_uuid4_jti() -> None:
    payload = {"lead_id": 1, "mode": "prospect", "language": "ru", "iat": NOW, "exp": NOW + 60}
    with pytest.raises(AgentContextError, match="malformed"):
        verify(sign({**payload, "jti": "not-a-uuid"}), KEY, now=clock)
    with pytest.raises(AgentContextError, match="malformed"):
        verify(sign({**payload, "jti": str(uuid.uuid1())}), KEY, now=clock)


@pytest.mark.parametrize(
    "token",
    [None, "", "abc", "abc.", ".sig", "a.b.c"],
    ids=["none", "empty", "no-dot", "no-sig", "no-payload", "garbage"],
)
def test_rejects_malformed(token: str | None) -> None:
    with pytest.raises(AgentContextError):
        verify(token, KEY, now=clock)


def test_rejects_wrong_key() -> None:
    with pytest.raises(AgentContextError, match="invalid signature"):
        verify(make(), OTHER_KEY, now=clock)


def test_rejects_tampered_payload_even_with_same_signature() -> None:
    payload, signature = make().split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=="))
    data["lead_id"] = 8
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    with pytest.raises(AgentContextError, match="invalid signature"):
        verify(f"{forged}.{signature}", KEY, now=clock)


@pytest.mark.parametrize(
    ("verify_at", "ok"),
    [(NOW, True), (NOW + 60, True), (NOW + 61, False), (NOW - 5, True), (NOW - 6, False)],
    ids=["now", "at-exp", "after-exp", "skew-ok", "issued-in-future"],
)
def test_ttl_and_skew(verify_at: float, ok: bool) -> None:
    token = make()
    if ok:
        verify(token, KEY, now=lambda: verify_at)
    else:
        with pytest.raises(AgentContextError):
            verify(token, KEY, now=lambda: verify_at)


def test_customer_mode_requires_client_id_on_issue() -> None:
    with pytest.raises(ValueError, match="client_id"):
        make(mode="customer")


def test_rejects_unknown_fields_signed_with_valid_key() -> None:
    payload = {"lead_id": 1, "mode": "prospect", "language": "ru", "iat": NOW, "exp": NOW + 60}
    payload["jti"] = str(uuid.uuid4())
    payload["role"] = "admin"
    with pytest.raises(AgentContextError, match="malformed"):
        verify(sign(payload), KEY, now=clock)
