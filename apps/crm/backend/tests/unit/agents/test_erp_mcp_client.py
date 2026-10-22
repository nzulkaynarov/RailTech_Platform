"""Клиент erp-mcp: разбор 401/429/400 вратаря и сбоев (Q-FIX36-1). Транспорт — MockTransport."""

import base64
import json
from typing import Any

import httpx2
import pytest
from asgi_correlation_id import correlation_id

from app.agents.erp_mcp import ErpMcpClient, ErpMcpError
from app.security.erp_agent_context import ErpScope
from tests.unit.agents.fake_erp_mcp import FakeErpMcp, rejection, tool_error, tool_ok

KEY = b"unit-test-key-not-a-secret-0123456789"
SCOPE = ErpScope(crm_client_id=7, erp_company_id=42, language="ru")
DEALS = [{"erp_deal_id": 5, "number": "D-5", "stage": "invoiced"}]


class Sleeper:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def make(fake: FakeErpMcp, sleeper: Sleeper | None = None, **kwargs: Any) -> ErpMcpClient:
    return ErpMcpClient(
        "http://erp-mcp:8104/mcp/erp",
        KEY,
        transport=fake.transport,
        sleep=sleeper or Sleeper(),
        **kwargs,
    )


def claims(token: str) -> dict[str, Any]:
    payload = token.partition(".")[0]
    decoded: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return decoded


def tool_attempts(fake: FakeErpMcp) -> int:
    return fake.methods.count("tools/call")


async def test_success_returns_unwrapped_result_with_scope_only_from_code() -> None:
    fake = FakeErpMcp(lambda name, args: tool_ok(DEALS))
    result = await make(fake).call("list_client_deals", {}, SCOPE)
    assert result == DEALS
    assert fake.tool_calls == [("list_client_deals", {})]
    seen = claims(fake.contexts[-1])
    assert (seen["crm_client_id"], seen["erp_company_id"], seen["mode"]) == (7, 42, "customer")
    assert seen["exp"] - seen["iat"] <= 60


async def test_request_id_of_the_crm_request_goes_with_every_mcp_request() -> None:
    fake = FakeErpMcp(lambda name, args: tool_ok(DEALS))
    token = correlation_id.set("0b6c2c46-aaaa-4bbb-8ccc-1234567890ab")
    try:
        await make(fake).call("list_client_deals", {}, SCOPE)
    finally:
        correlation_id.reset(token)
    assert set(fake.request_ids) == {"0b6c2c46-aaaa-4bbb-8ccc-1234567890ab"}


async def test_outside_a_request_the_mcp_call_gets_a_fresh_request_id() -> None:
    fake = FakeErpMcp(lambda name, args: tool_ok(DEALS))
    client = make(fake)
    await client.call("list_client_deals", {}, SCOPE)
    await client.call("list_client_deals", {}, SCOPE)
    first, second = (
        set(fake.request_ids[: len(fake.request_ids) // 2]),
        set(fake.request_ids[len(fake.request_ids) // 2 :]),
    )
    assert len(first) == len(second) == 1
    assert first != second


async def test_401_issues_new_context_and_retries_once() -> None:
    fake = FakeErpMcp(lambda name, args: tool_ok(DEALS))
    fake.reject(rejection(401, "INVALID_AGENT_CONTEXT"), on="tools/call")  # jti уже погашен
    result = await make(fake).call("list_client_deals", {}, SCOPE)
    assert result == DEALS
    assert tool_attempts(fake) == 2
    pairs = zip(fake.contexts, fake.methods, strict=True)
    tool_jtis = [claims(c)["jti"] for c, m in pairs if m == "tools/call"]
    assert len(set(tool_jtis)) == 2


async def test_401_twice_gives_up_after_one_retry() -> None:
    fake = FakeErpMcp()
    fake.reject_always(rejection(401, "INVALID_AGENT_CONTEXT"), on="tools/call")
    with pytest.raises(ErpMcpError) as raised:
        await make(fake).call("list_client_deals", {}, SCOPE)
    assert raised.value.kind == "context_rejected"
    assert tool_attempts(fake) == 2  # один повтор, не больше


async def test_401_on_every_request_gives_up_after_one_retry() -> None:
    fake = FakeErpMcp()
    fake.reject_always(
        rejection(401, "INVALID_AGENT_CONTEXT")
    )  # неверный ключ: отказ с первого запроса
    with pytest.raises(ErpMcpError) as raised:
        await make(fake).call("list_client_deals", {}, SCOPE)
    assert raised.value.kind == "context_rejected"
    assert fake.methods.count("initialize") == 2
    assert len({claims(c)["jti"] for c in fake.contexts}) == 2


async def test_result_level_invalid_context_is_retried_once() -> None:
    fake = FakeErpMcp(lambda name, args: tool_error("INVALID_AGENT_CONTEXT"))
    with pytest.raises(ErpMcpError) as raised:
        await make(fake).call("list_client_deals", {}, SCOPE)
    assert raised.value.kind == "context_rejected"
    assert tool_attempts(fake) == 2


async def test_429_waits_retry_after_then_succeeds() -> None:
    fake = FakeErpMcp(lambda name, args: tool_ok(DEALS))
    fake.reject(rejection(429, "TOO_MANY_REQUESTS", **{"Retry-After": "2"}), on="tools/call")
    sleeper = Sleeper()
    result = await make(fake, sleeper).call("list_client_deals", {}, SCOPE)
    assert result == DEALS
    assert sleeper.waits == [2.0]


async def test_429_wait_is_bounded_by_retry_count() -> None:
    fake = FakeErpMcp()
    fake.reject_always(rejection(429, "TOO_MANY_REQUESTS", **{"Retry-After": "1"}), on="tools/call")
    sleeper = Sleeper()
    with pytest.raises(ErpMcpError) as raised:
        await make(fake, sleeper, rate_retries=2).call("list_client_deals", {}, SCOPE)
    assert raised.value.kind == "rate_limited"
    assert sleeper.waits == [1.0, 1.0]


async def test_429_with_too_long_retry_after_does_not_wait() -> None:
    fake = FakeErpMcp()
    fake.reject_always(
        rejection(429, "TOO_MANY_REQUESTS", **{"Retry-After": "120"}), on="tools/call"
    )
    sleeper = Sleeper()
    with pytest.raises(ErpMcpError) as raised:
        await make(fake, sleeper, max_wait_s=5).call("list_client_deals", {}, SCOPE)
    assert raised.value.kind == "rate_limited"
    assert sleeper.waits == []


async def test_429_without_retry_after_uses_short_default() -> None:
    fake = FakeErpMcp(lambda name, args: tool_ok(DEALS))
    fake.reject(rejection(429, "TOO_MANY_REQUESTS"), on="tools/call")
    sleeper = Sleeper()
    await make(fake, sleeper).call("list_client_deals", {}, SCOPE)
    assert sleeper.waits == [1.0]


async def test_400_is_not_retried() -> None:
    fake = FakeErpMcp()
    fake.reject_always(rejection(400, "INVALID_ARGUMENTS"), on="tools/call")
    with pytest.raises(ErpMcpError) as raised:
        await make(fake).call("get_deal_status", {"erp_deal_id": "x"}, SCOPE)
    assert raised.value.kind == "invalid_arguments"
    assert tool_attempts(fake) == 1


async def test_result_level_invalid_arguments_is_not_retried() -> None:
    fake = FakeErpMcp(lambda name, args: tool_error("INVALID_ARGUMENTS"))
    with pytest.raises(ErpMcpError) as raised:
        await make(fake).call("get_deal_status", {}, SCOPE)
    assert raised.value.kind == "invalid_arguments"
    assert tool_attempts(fake) == 1


@pytest.mark.parametrize(
    "code", ["TOOL_NOT_AVAILABLE_IN_MODE", "TOOL_EXECUTION_ERROR", "INTERNAL_ERROR"]
)
async def test_tool_errors_are_reported_without_retry(code: str) -> None:
    fake = FakeErpMcp(lambda name, args: tool_error(code))
    with pytest.raises(ErpMcpError) as raised:
        await make(fake).call("list_client_deals", {}, SCOPE)
    assert (raised.value.kind, raised.value.code) == ("tool_error", code)
    assert tool_attempts(fake) == 1


async def test_network_failure_is_unavailable_without_retry() -> None:
    fake = FakeErpMcp()
    fake.reject_always(httpx2.ConnectError("connection refused"))
    with pytest.raises(ErpMcpError) as raised:
        await make(fake).call("list_client_deals", {}, SCOPE)
    assert raised.value.kind == "unavailable"
    assert len(fake.contexts) == 1  # без повтора


async def test_server_error_is_unavailable_without_retry() -> None:
    fake = FakeErpMcp()
    fake.reject_always(httpx2.Response(503, text="bad gateway"), on="tools/call")
    with pytest.raises(ErpMcpError) as raised:
        await make(fake).call("list_client_deals", {}, SCOPE)
    assert (raised.value.kind, raised.value.code) == ("unavailable", "HTTP_503")
    assert tool_attempts(fake) == 1


def test_bot_gets_a_client_only_when_erp_mcp_is_enabled_and_keyed() -> None:
    from types import SimpleNamespace

    from pydantic import SecretStr

    from app.bot.setup import _erp_mcp
    from app.config import Settings

    def container(**overrides: Any) -> Any:
        return SimpleNamespace(settings=Settings(_env_file=None, **overrides))

    key = SecretStr("k" * 32)
    assert isinstance(
        _erp_mcp(container(erp_mcp_enabled=True, erp_mcp_context_key=key)), ErpMcpClient
    )
    assert _erp_mcp(container(erp_mcp_enabled=True)) is None
    assert _erp_mcp(container(erp_mcp_context_key=key)) is None


@pytest.mark.parametrize("status", [401, 429, 400, 503])
async def test_context_and_key_never_reach_the_logs(
    status: int, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeErpMcp()
    fake.reject_always(rejection(status, "x", **{"Retry-After": "1"}), on="tools/call")
    with caplog.at_level("DEBUG"), pytest.raises(ErpMcpError):
        await make(fake).call("list_client_deals", {}, SCOPE)
    seen = caplog.text + "".join(capsys.readouterr())
    assert fake.contexts  # вызовы были, а значит, было что утекать
    assert KEY.decode() not in seen
    for context in set(fake.contexts):
        assert context not in seen
        assert context.partition(".")[2] not in seen  # подпись
