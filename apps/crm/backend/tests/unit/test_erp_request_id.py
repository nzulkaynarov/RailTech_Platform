"""`X-Request-ID` и общий HTTP-клиент во всех вызовах CRM -> ERP (S0-6, ADR-0017).

Идентификатор запроса CRM уходит в ERP заголовком, вне запроса (воркер) - новый UUID на вызов;
клиент `httpx` один на процесс, таймаут - на вызов; ошибки (429, 401/403, таймаут) прежние.
"""

import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
import respx
import structlog
from asgi_correlation_id import correlation_id

from app.config import Settings
from app.container import Container
from app.domain.errors import ErpRateLimitedError, Reason, UpstreamUnavailableError
from app.integrations.erp import (
    ErpConnection,
    HttpxErpClient,
    HttpxErpProbe,
)
from app.integrations.erp_company import HttpxErpCompanyClient
from app.integrations.erp_externals import HttpxErpSwitchClient
from app.integrations.erp_pairing import HttpxErpPairingClient, PairingSecrets
from app.integrations.erp_transport import REQUEST_ID_HEADER, SharedAsyncClient
from app.integrations.erp_users import HttpxErpUsersClient, ProvisionPayload
from tests.unit.test_erp_handoff import _DummyStore, _sample_payload

BASE = "https://erp.internal"
API = f"{BASE}/api/integration/v1"
CONFIG = Settings(_env_file=None, erp_base_url=BASE, erp_service_token="t")
HEALTHY = {
    "status": "ok",
    "version": "1.0.0",
    "migrations_applied": True,
    "queue_alive": True,
    "checked_at": "2026-10-22T10:00:00Z",
}
USER = ProvisionPayload(
    crm_user_id=42, email="m@railtech.uz", name="М", role="backoffice", permissions=()
)
SECRETS = PairingSecrets.generate()

Call = Callable[[SharedAsyncClient], Awaitable[object]]


def _routes(mock: respx.MockRouter) -> None:
    """Ответы ERP на все вызовы ниже; запросы разбирает `calls`."""
    mock.post(f"{API}/clients/handoff").respond(201, json={"erp_company_id": 1})
    mock.get(f"{API}/companies/7/summary").respond(200, json={"receivables_by_currency": []})
    mock.post(f"{API}/users/provision").respond(201, json={"erp_user_id": 7})
    mock.delete(f"{API}/users/42/sessions").respond(204)
    mock.put(f"{API}/externals/mail/switch").respond(200, json={"code": "mail"})
    mock.get(f"{API}/health").respond(200, json=HEALTHY)
    mock.post(f"{API}/pairing/rotate").respond(
        200,
        json={
            "rotated": True,
            "rotated_at": "2026-10-22T10:00:00+05:00",
            "previous_token_valid_until": "2026-10-22T11:00:00+05:00",
        },
    )


async def _handoff(http: SharedAsyncClient) -> object:
    return await HttpxErpClient(_DummyStore("t"), CONFIG, http=http).handoff_client(
        _sample_payload()
    )


async def _company(http: SharedAsyncClient) -> object:
    return await HttpxErpCompanyClient(_DummyStore("t"), CONFIG, http=http).receivables(7)


async def _provision(http: SharedAsyncClient) -> object:
    return await HttpxErpUsersClient(_DummyStore("t"), CONFIG, http=http).provision_user(USER)


async def _revoke(http: SharedAsyncClient) -> object:
    return await HttpxErpUsersClient(_DummyStore("t"), CONFIG, http=http).revoke_sessions(42)


async def _switch(http: SharedAsyncClient) -> object:
    client = HttpxErpSwitchClient(_DummyStore("t"), CONFIG, http=http)
    await client.set_switch("mail", enabled=False, reason="тест")
    return None


async def _probe(http: SharedAsyncClient) -> object:
    return await HttpxErpProbe(http=http).health(ErpConnection(base_url=BASE, token="t"))


async def _rotate(http: SharedAsyncClient) -> object:
    return await HttpxErpPairingClient(http=http).rotate(BASE, "t", SECRETS)


ALL_CALLS = [_handoff, _company, _provision, _revoke, _switch, _probe, _rotate]
IDS = [c.__name__.lstrip("_") for c in ALL_CALLS]


@pytest.fixture
def clean_context() -> Iterator[None]:
    token = correlation_id.set(None)
    yield
    correlation_id.reset(token)


@pytest.mark.parametrize("call", ALL_CALLS, ids=IDS)
async def test_request_id_of_the_crm_request_goes_to_erp(call: Call, clean_context: None) -> None:
    correlation_id.set("0b6c2c46-aaaa-4bbb-8ccc-1234567890ab")
    with respx.mock(assert_all_called=False) as mock:
        _routes(mock)
        await call(SharedAsyncClient())
        assert len(mock.calls) == 1
        sent = mock.calls.last.request.headers
    assert sent[REQUEST_ID_HEADER] == "0b6c2c46-aaaa-4bbb-8ccc-1234567890ab"


@pytest.mark.parametrize("call", ALL_CALLS, ids=IDS)
async def test_outside_a_request_each_call_gets_a_new_uuid_and_a_log_line(
    call: Call, clean_context: None
) -> None:
    http = SharedAsyncClient()
    with respx.mock(assert_all_called=False) as mock, structlog.testing.capture_logs() as logs:
        _routes(mock)
        await call(http)
        await call(http)
        ids = [c.request.headers[REQUEST_ID_HEADER] for c in mock.calls]
    assert len(ids) == 2
    assert all(uuid.UUID(i).version == 4 for i in ids)
    assert ids[0] != ids[1]
    logged = [e["request_id"] for e in logs if e["event"] == "erp_http_call"]
    assert logged == ids
    assert all(e["status"] in (200, 201, 204) for e in logs if e["event"] == "erp_http_call")


async def test_one_client_is_reused_and_the_timeout_is_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[httpx.AsyncClient] = []

    class Counting(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", Counting)
    http = SharedAsyncClient()
    timeouts: list[float | None] = []

    def seen(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json=HEALTHY)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{API}/health").mock(side_effect=seen)
        for _ in range(3):
            await _probe(http)
        await HttpxErpProbe(timeout_s=1.5, http=http).health(
            ErpConnection(base_url=BASE, token="t")
        )
        assert len(created) == 1  # три вызова пробы и один с другим таймаутом - один клиент
        assert timeouts == [5.0, 5.0, 5.0, 1.5]
        await http.aclose()
        assert created[0].is_closed
        await _probe(http)  # после закрытия клиент создаётся заново, вызов не падает
    assert len(created) == 2
    await http.aclose()


async def test_container_gives_every_erp_client_the_same_http_client() -> None:
    container = Container(Settings(_env_file=None))
    clients: list[Any] = [
        container.erp_client,
        container.erp_switch_client,
        container.erp_access_service._client,
        container.erp_client_card._erp,
        container.erp_connector._probe,
        container.erp_pairing._client,
    ]
    assert {id(c._http) for c in clients} == {id(container.erp_http)}
    client = container.erp_http.get()
    await container.aclose()
    assert client.is_closed


async def test_rate_limit_still_carries_retry_after(clean_context: None) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{API}/companies/7/summary").respond(429, headers={"Retry-After": "17"})
        with pytest.raises(ErpRateLimitedError) as excinfo:
            await _company(SharedAsyncClient())
    assert excinfo.value.retry_after_s == 17


@pytest.mark.parametrize("status", [401, 403])
async def test_unauthorized_is_still_erp_unauthorized(status: int, clean_context: None) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{API}/clients/handoff").respond(status)
        with pytest.raises(UpstreamUnavailableError) as excinfo:
            await _handoff(SharedAsyncClient())
    assert excinfo.value.details["reason"] == Reason.ERP_UNAUTHORIZED


async def test_timeout_is_still_erp_unavailable_and_is_logged_with_the_id(
    clean_context: None,
) -> None:
    with respx.mock(assert_all_called=False) as mock, structlog.testing.capture_logs() as logs:
        mock.post(f"{API}/clients/handoff").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(UpstreamUnavailableError) as excinfo:
            await _handoff(SharedAsyncClient())
        sent = mock.calls.last.request.headers[REQUEST_ID_HEADER]
    assert excinfo.value.details["reason"] == Reason.ERP_UNAVAILABLE
    failed = [e for e in logs if e["event"] == "erp_http_call"]
    assert failed[0]["request_id"] == sent
    assert failed[0]["error"] == "ReadTimeout"


async def test_log_line_has_no_secrets(clean_context: None) -> None:
    with respx.mock(assert_all_called=False) as mock, structlog.testing.capture_logs() as logs:
        _routes(mock)
        await _handoff(SharedAsyncClient())
    dumped = json.dumps(logs, default=str)
    assert "Bearer" not in dumped
    assert "erp.internal" not in dumped  # адрес сервера не нужен: путь и статус достаточно
    assert "/api/integration/v1/clients/handoff" in dumped
