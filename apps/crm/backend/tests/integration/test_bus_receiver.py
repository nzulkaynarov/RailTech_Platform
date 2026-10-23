"""Приёмник шины `POST /bus/v1/events` в приложении CRM (B4, CONTRACTS §9.1): подпись и окно,
повтор id, неизвестный тип, корреляция, старый маршрут вебхуков ERP удалён.

Библиотечные правила приёма проверяет сама `rt_bus`; здесь — что приёмник подключён к приложению,
берёт секреты пары из окружения и из секретов вебхуков сопряжения и передаёт корреляцию событию.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from rt_bus import get_correlation_id
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus.secrets import derive_pair_secret
from app.config import Settings
from app.main import create_app
from app.security.secrets_store import ERP_WEBHOOK_SECRET, SecretCipher, SecretsStore
from app.services.erp_events import ErpEventsService
from tests.bus_events import example_envelope, signed_raw, signed_request
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration

URL = "/bus/v1/events"
PAIR = "bus-receiver-test-pair-secret-0001"  # фиктивный секрет пары erp → crm
TYPE = "uz.railtech.erp.quote.viewed.v1"


@pytest.fixture
def api(live_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("RT_BUS_SECRET_ERP_CRM", PAIR)
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def envelope(**changes: Any) -> dict[str, Any]:
    body = example_envelope(TYPE)
    body["id"] = str(uuid.uuid4())
    body.update(changes)
    return body


def post(
    api: TestClient, body: dict[str, Any], *, secret: str = PAIR, now: datetime | None = None
) -> Any:
    headers, raw = signed_request(body, secret, now=now)
    return api.post(URL, content=raw, headers=headers)


async def inbox_count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(await session.scalar(text("SELECT count(*) FROM rt_bus_inbox")) or 0)


async def test_a_signed_event_is_accepted_stored_once_and_queued(
    sessions: async_sessionmaker[AsyncSession], api: TestClient
) -> None:
    body = envelope()

    first = post(api, body)
    again = post(api, body)

    assert (first.status_code, first.json()) == (200, {"status": "received", "id": body["id"]})
    assert (again.status_code, again.json()["status"]) == (200, "duplicate")
    assert await inbox_count(sessions) == 1


@pytest.mark.parametrize(
    "case",
    ["no-signature", "wrong-secret", "unknown-publisher", "stale", "future", "foreign-source"],
)
async def test_an_unsigned_or_forged_delivery_is_401_and_stores_nothing(
    sessions: async_sessionmaker[AsyncSession], api: TestClient, case: str
) -> None:
    body = envelope()
    headers, raw = signed_request(body, PAIR)
    if case == "no-signature":
        del headers["X-RT-Signature"]
    elif case == "wrong-secret":
        headers, raw = signed_request(body, "some-other-secret-value")
    elif case == "unknown-publisher":
        headers, raw = signed_request(body, PAIR, publisher="stranger")
    elif case == "stale":
        headers, raw = signed_request(body, PAIR, now=datetime.now(UTC) - timedelta(seconds=400))
    elif case == "future":
        headers, raw = signed_request(body, PAIR, now=datetime.now(UTC) + timedelta(seconds=400))
    else:
        body["source"] = "rt://crm"  # издатель erp не вправе подписывать чужой source
        headers, raw = signed_request(body, PAIR)

    response = api.post(URL, content=raw, headers=headers)

    assert response.status_code == 401
    assert await inbox_count(sessions) == 0


async def test_a_signed_body_that_is_not_json_or_not_an_envelope_is_400(
    sessions: async_sessionmaker[AsyncSession], api: TestClient
) -> None:
    event_id = str(uuid.uuid4())
    for raw in (b"garbage", json.dumps({"hello": "world"}).encode()):
        headers = signed_raw(raw, event_id, PAIR)
        assert api.post(URL, content=raw, headers=headers).status_code == 400
    assert await inbox_count(sessions) == 0


async def test_an_event_whose_data_breaks_the_schema_is_422(
    sessions: async_sessionmaker[AsyncSession], api: TestClient
) -> None:
    body = envelope()
    del body["data"]["payload"]["erp_quote_id"]
    assert post(api, body).status_code == 422
    assert await inbox_count(sessions) == 0


async def test_an_unknown_type_is_recorded_as_skipped_with_200(
    sessions: async_sessionmaker[AsyncSession], api: TestClient
) -> None:
    body = envelope(
        type="uz.railtech.erp.warehouse.exploded.v1",
        dataschema="rt://contracts/events/erp/warehouse.exploded/v1",
    )

    response = post(api, body)

    assert (response.status_code, response.json()["status"]) == (200, "skipped")
    async with sessions() as session:
        status = await session.scalar(text("SELECT status FROM rt_bus_inbox"))
    assert status == "skipped"


async def test_events_of_this_service_are_not_accepted_from_the_outside(
    sessions: async_sessionmaker[AsyncSession], api: TestClient
) -> None:
    """CRM не подписана на свои события: чужой издатель `crm` без секрета пары — 401."""
    body = example_envelope("uz.railtech.crm.client.updated.v1")
    headers, raw = signed_request(body, PAIR, publisher="crm")
    assert api.post(URL, content=raw, headers=headers).status_code == 401


async def test_the_old_erp_webhook_route_is_gone_and_the_receiver_is_not_in_the_openapi(
    api: TestClient,
) -> None:
    old = api.post("/api/v1/integrations/erp/events", content=b"{}")
    assert old.status_code in (404, 405)
    assert "/api/v1/integrations/erp/events" not in api.get("/openapi.json").text
    assert URL not in api.get("/openapi.json").json()["paths"]


async def test_the_correlation_id_of_the_event_reaches_the_handler(
    sessions: async_sessionmaker[AsyncSession],
    api: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    async def spy(self: ErpEventsService, session: Any, event: Any) -> bool:
        seen.append(get_correlation_id())
        return True

    monkeypatch.setattr(ErpEventsService, "apply", spy)
    body = envelope(correlationid="corr-from-erp-0042")
    assert post(api, body).status_code == 200

    from app.container import get_container

    container = cast(Any, api.app).state.container
    assert container is not get_container()
    status = await container.bus.process_inbox(body["id"])

    assert status == "processed"
    assert seen == ["corr-from-erp-0042"]


async def test_the_pair_secret_is_derived_from_the_pairing_webhook_secret(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без `RT_BUS_SECRET_ERP_CRM` секрет пары выводится из секрета вебхуков «Подключений» (L12)."""
    monkeypatch.delenv("RT_BUS_SECRET_ERP_CRM", raising=False)
    settings = live_settings.model_copy(update={"secrets_key": SecretStr("k" * 64)})
    webhook = "pairing-webhook-secret-for-the-bus-0001"  # фиктивный
    store = SecretsStore(sessions, SecretCipher.optional(settings.secrets_key.get_secret_value()))
    async with sessions() as session, session.begin():
        await store.put(session, ERP_WEBHOOK_SECRET, webhook, None)
    account, password = await make_user(sessions, "bus-pair@railtech.uz", ["admin"])
    assert password == PASSWORD
    with TestClient(create_app(settings)) as api:
        login(api, account.email, password)
        body = envelope()
        derived = derive_pair_secret(webhook, "erp", "crm")

        assert post(api, body, secret=derived).status_code == 200
        assert post(api, envelope(), secret=webhook).status_code == 401, "сам секрет не годится"
