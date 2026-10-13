import base64
import json

import pytest

from app.security.agent_context import AgentContextError, issue, verify

KEY = b"k" * 32
OTHER_KEY = b"x" * 32
NOW = 1_800_000_000.0


def clock(value: float = NOW) -> float:
    return value


def make(**overrides: object) -> str:
    params: dict[str, object] = {"lead_id": 7, "mode": "prospect", "language": "ru"}
    params.update(overrides)
    return issue(KEY, now=clock, **params)  # type: ignore[arg-type]


def test_roundtrip() -> None:
    context = verify(make(client_id=3, mode="customer"), KEY, now=clock)
    assert (context.lead_id, context.client_id, context.mode) == (7, 3, "customer")
    assert context.exp - context.iat == 60


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
    payload["role"] = "admin"
    import hashlib
    import hmac

    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(KEY, body.encode(), hashlib.sha256).digest())
    with pytest.raises(AgentContextError, match="malformed"):
        verify(f"{body}.{sig.rstrip(b'=').decode()}", KEY, now=clock)
