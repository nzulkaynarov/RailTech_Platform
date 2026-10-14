"""Пробы центра внешних сервисов (M3-CRM-12, ADR-0024): Telegram, health, Langfuse, LiteLLM admin.

HTTP подставной (respx): успех, 401, таймаут, недоступен. Токен Telegram — только в пути запроса.
"""

import json

import httpx
import pytest
import respx
from pydantic import AnyHttpUrl, SecretStr

from app.integrations import external_probes as probes
from app.integrations.litellm_admin import LiteLLMAdmin, LiteLLMAdminError, ProviderBudget

TG = "https://api.telegram.org"
TOKEN = "123456:fake-test-token"  # фиктивный, в сеть не уходит
LITELLM = "http://litellm.invalid:4000"


def tg(method: str) -> str:
    return f"{TG}/bot{TOKEN}/{method}"


@respx.mock
async def test_telegram_ok_reads_webhook_info() -> None:
    respx.get(tg("getMe")).mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"username": "rt_bot"}})
    )
    respx.get(tg("getWebhookInfo")).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "url": "https://crm.example/telegram/webhook",
                    "pending_update_count": 3,
                    "last_error_date": 1791955830,
                    "last_error_message": "Connection timed out",
                },
            },
        )
    )
    async with httpx.AsyncClient() as client:
        p = await probes.telegram(client, TOKEN)
    assert p.error is None
    assert (p.username, p.pending_updates) == ("rt_bot", 3)
    assert p.webhook_url == "https://crm.example/telegram/webhook"
    assert p.last_error_message == "Connection timed out"
    assert p.last_error_at is not None
    assert p.last_error_at.year == 2026
    assert p.latency_ms is not None


@pytest.mark.parametrize("status", [401, 404])
@respx.mock
async def test_telegram_rejected_token(status: int) -> None:
    respx.get(tg("getMe")).mock(return_value=httpx.Response(status, json={"ok": False}))
    async with httpx.AsyncClient() as client:
        p = await probes.telegram(client, TOKEN)
    assert p.error == "unauthorized"
    assert p.detail == f"getMe: HTTP {status}"
    assert TOKEN not in (p.detail or "")


@pytest.mark.parametrize(
    ("exc", "kind"),
    [(httpx.ConnectTimeout("t"), "timeout"), (httpx.ConnectError("refused"), "unavailable")],
)
@respx.mock
async def test_telegram_network_errors(exc: Exception, kind: str) -> None:
    respx.get(tg("getMe")).mock(side_effect=exc)
    async with httpx.AsyncClient() as client:
        p = await probes.telegram(client, TOKEN)
    assert p.error == kind
    assert TOKEN not in (p.detail or "")


@respx.mock
async def test_telegram_server_error_is_bad_response() -> None:
    respx.get(tg("getMe")).mock(return_value=httpx.Response(502))
    async with httpx.AsyncClient() as client:
        assert (await probes.telegram(client, TOKEN)).error == "bad_response"


@pytest.mark.parametrize(
    ("response", "error", "detail"),
    [
        (httpx.Response(200, json={"status": "ok"}), None, None),
        (httpx.Response(401), "unauthorized", "HTTP 401"),
        (httpx.Response(503), "bad_response", "HTTP 503"),
    ],
)
@respx.mock
async def test_http_health(response: httpx.Response, error: str | None, detail: str | None) -> None:
    respx.get("http://docling:5001/health").mock(return_value=response)
    async with httpx.AsyncClient() as client:
        facts = await probes.http_health(client, "http://docling:5001/health")
    assert (facts.error, facts.detail) == (error, detail)
    assert facts.latency_ms is not None


@respx.mock
async def test_http_health_timeout_and_unreachable() -> None:
    respx.get("http://rustfs:9000/health").mock(side_effect=httpx.ReadTimeout("slow"))
    respx.get("http://docling:5001/health").mock(side_effect=httpx.ConnectError("refused"))
    async with httpx.AsyncClient() as client:
        slow = await probes.http_health(client, "http://rustfs:9000/health")
        down = await probes.http_health(client, "http://docling:5001/health")
    assert (slow.error, slow.detail) == ("timeout", "ReadTimeout")
    assert (down.error, down.detail) == ("unavailable", "ConnectError")


@pytest.mark.parametrize(("status", "keys_ok"), [(200, True), (401, False), (403, False)])
@respx.mock
async def test_langfuse_checks_keys_without_writing(status: int, keys_ok: bool) -> None:
    respx.get("http://langfuse:3000/api/public/health").mock(
        return_value=httpx.Response(200, json={"status": "OK"})
    )
    projects = respx.get("http://langfuse:3000/api/public/projects").mock(
        return_value=httpx.Response(status, json={"data": []})
    )
    async with httpx.AsyncClient() as client:
        health, ok = await probes.langfuse(client, "http://langfuse:3000/", "pk-lf-x", "sk-lf-y")
    assert health.error is None
    assert ok is keys_ok
    assert projects.calls.last.request.headers["authorization"].startswith("Basic ")
    assert not any(c.request.method == "POST" for c in respx.calls)


@respx.mock
async def test_langfuse_down_skips_key_check() -> None:
    respx.get("http://langfuse:3000/api/public/health").mock(side_effect=httpx.ConnectError("x"))
    async with httpx.AsyncClient() as client:
        health, ok = await probes.langfuse(client, "http://langfuse:3000", "pk", "sk")
    assert health.error == "unavailable"
    assert ok is None


def admin() -> LiteLLMAdmin:
    return LiteLLMAdmin(AnyHttpUrl(LITELLM), SecretStr("sk-master-test"))


@respx.mock
async def test_provider_budgets_recorded_shape() -> None:
    """Ответ `/provider/budgets` LiteLLM v1.105.0 (одноразовый прокси, ADR-0024 п. 2)."""
    respx.get(f"{LITELLM}/provider/budgets").mock(
        return_value=httpx.Response(
            200,
            json={
                "providers": {
                    "anthropic": {
                        "budget_limit": 3.0,
                        "time_period": "1d",
                        "spend": 0.42,
                        "budget_reset_at": "2026-10-15T00:00:00+00:00",
                    },
                    "gemini": {"budget_limit": 1.0, "time_period": "1d", "spend": 0.0},
                }
            },
        )
    )
    budgets = await admin().provider_budgets()
    assert budgets == {
        "anthropic": ProviderBudget(spend=0.42, limit=3.0),
        "gemini": ProviderBudget(spend=0.0, limit=1.0),
    }


@respx.mock
async def test_provider_budgets_without_config_is_empty_not_error() -> None:
    respx.get(f"{LITELLM}/provider/budgets").mock(
        return_value=httpx.Response(
            500, json={"error": {"message": "No provider budget config found. Please set …"}}
        )
    )
    assert await admin().provider_budgets() == {}


@respx.mock
async def test_provider_budgets_unauthorized_raises() -> None:
    respx.get(f"{LITELLM}/provider/budgets").mock(return_value=httpx.Response(401))
    with pytest.raises(LiteLLMAdminError):
        await admin().provider_budgets()


@respx.mock
async def test_router_aliases_read_and_replace() -> None:
    respx.get(f"{LITELLM}/router/settings").mock(
        return_value=httpx.Response(
            200,
            json={"current_values": {"model_group_alias": {"dialog-model": "fallback-model"}}},
        )
    )
    update = respx.post(f"{LITELLM}/config/update").mock(
        return_value=httpx.Response(200, json={"message": "Config updated successfully"})
    )
    client = admin()
    assert await client.router_aliases() == {"dialog-model": "fallback-model"}
    await client.set_router_aliases({})
    body = json.loads(update.calls.last.request.content)
    assert body == {"router_settings": {"model_group_alias": {}}}
    assert update.calls.last.request.headers["authorization"] == "Bearer sk-master-test"


@respx.mock
async def test_block_and_unblock_deployment() -> None:
    block = respx.post(f"{LITELLM}/model/block").mock(return_value=httpx.Response(200, json={}))
    unblock = respx.post(f"{LITELLM}/model/unblock").mock(return_value=httpx.Response(200, json={}))
    await admin().block("rt-embed-model-1")
    await admin().unblock("rt-embed-model-1")
    assert json.loads(block.calls.last.request.content) == {"model_id": "rt-embed-model-1"}
    assert json.loads(unblock.calls.last.request.content) == {"model_id": "rt-embed-model-1"}


@respx.mock
async def test_gateway_unreachable_raises_safe_error() -> None:
    respx.post(f"{LITELLM}/config/update").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(LiteLLMAdminError) as caught:
        await admin().set_router_aliases({"dialog-model": "fallback-model"})
    assert caught.value.status is None
    assert caught.value.detail == "ConnectError"
