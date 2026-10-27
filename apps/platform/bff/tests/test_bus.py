"""BFF — подписчик шины (B5): подписка в контракте, приёмник `POST /bus/v1/events`, подсказка."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from rt_bus.signing import format_timestamp

from app.bus import SERVICE, SUBSCRIBED, topics_for
from app.hub import CHANNEL, TOPICS
from tests.bus_support import CRM_SECRET, SECRET, delivery, envelope
from tests.conftest import Web

SUBSCRIPTIONS = Path(__file__).resolve().parents[4] / "packages/contracts/bus/subscriptions.yaml"


@pytest.fixture(autouse=True)
def pair_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_ERP_PLATFORM_BFF", SECRET)
    monkeypatch.setenv("RT_BUS_SECRET_CRM_PLATFORM_BFF", CRM_SECRET)


async def post(web: Web, headers: dict[str, str], raw: bytes) -> tuple[int, dict[str, str]]:
    response = await web.client.post("/bus/v1/events", content=raw, headers=headers)
    return response.status_code, response.json()


def hints(web: Web) -> list[dict[str, object]]:
    return [json.loads(m) for ch, m in web.redis.published if ch == CHANNEL]


def test_subscription_row_matches_the_handlers() -> None:
    rows = {s["name"]: s for s in yaml.safe_load(SUBSCRIPTIONS.read_text("utf-8"))["subscribers"]}
    row = rows[SERVICE]
    assert row["endpoint"] == "http://platform-bff:8000/bus/v1/events"
    assert row["endpoint_env"] == "RT_BUS_ENDPOINT_PLATFORM_BFF"
    assert tuple(row["types"]) == SUBSCRIBED


def test_every_subscribed_type_maps_to_known_topics() -> None:
    erp = ("notifications", "counters", "queue", "activity")
    assert topics_for("uz.railtech.erp.quote.sent.v1") == erp
    assert topics_for("uz.railtech.crm.lead.created.v1") == (
        "counters",
        "queue",
        "activity",
        "messages",
    )
    # D1-1: сообщение в переписке — «Ждут ответа», бейдж и «Моя очередь», не лента «Сегодня»
    message = "uz.railtech.crm.lead.message_added.v1"
    assert topics_for(message, {"handoff": True}) == ("counters", "queue", "messages")
    # диалог с ботом: счётчики и «Моя очередь» не меняются — только переписка
    assert topics_for(message, {"handoff": False}) == ("messages",)
    assert set(TOPICS) == {*erp, "messages"}
    assert topics_for("uz.railtech.identity.user.updated.v1") == ("counters", "queue")
    assert topics_for("uz.railtech.crm.client.updated.v1") == ()


async def test_signed_erp_event_becomes_a_hint(web: Web) -> None:
    headers, raw = delivery(envelope("erp", "quote.sent"))
    status, body = await post(web, headers, raw)
    assert (status, body["status"]) == (200, "processed")
    assert hints(web) == [
        {
            "topics": ["notifications", "counters", "queue", "activity"],
            "reason": "uz.railtech.erp.quote.sent.v1",
        }
    ]


async def test_crm_lead_event_hints_counters_and_queue(web: Web) -> None:
    headers, raw = delivery(envelope("crm", "lead.created"), publisher="crm", secret=CRM_SECRET)
    status, _ = await post(web, headers, raw)
    assert status == 200
    assert hints(web) == [
        {
            "topics": ["counters", "queue", "activity", "messages"],
            "reason": "uz.railtech.crm.lead.created.v1",
        }
    ]


async def test_duplicate_delivery_does_not_repeat_the_hint(web: Web) -> None:
    headers, raw = delivery(envelope("erp", "invoice.paid"))
    assert (await post(web, headers, raw))[1]["status"] == "processed"
    assert (await post(web, headers, raw))[1]["status"] == "duplicate"
    assert len(hints(web)) == 1


async def test_eds_event_is_skipped_until_the_screens_of_stage_d(
    web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Волна 12: подписка на события EDS есть, обработчика нет — 200 `skipped`, подсказки нет."""
    monkeypatch.setenv("RT_BUS_SECRET_EDS_PLATFORM_BFF", "test-pair-secret-eds-platform-bff")
    headers, raw = delivery(
        envelope("eds", "letter.registered"),
        publisher="eds",
        secret="test-pair-secret-eds-platform-bff",
    )
    status, body = await post(web, headers, raw)
    assert (status, body["status"]) == (200, "skipped")
    assert hints(web) == []


async def test_event_without_a_handler_is_skipped(web: Web) -> None:
    headers, raw = delivery(envelope("crm", "client.updated"), publisher="crm", secret=CRM_SECRET)
    status, body = await post(web, headers, raw)
    assert (status, body["status"]) == (200, "skipped")
    assert hints(web) == []


async def test_bad_signature_is_refused(web: Web) -> None:
    headers, raw = delivery(envelope("erp", "quote.sent"), secret="not-the-pair-secret")
    status, _ = await post(web, headers, raw)
    assert status == 401
    assert hints(web) == []


async def test_event_signed_outside_the_window_is_refused(web: Web) -> None:
    stale = format_timestamp(datetime.now(UTC) - timedelta(minutes=10))
    headers, raw = delivery(envelope("erp", "quote.sent"), timestamp=stale)
    assert (await post(web, headers, raw))[0] == 401


async def test_unknown_publisher_and_foreign_source_are_refused(web: Web) -> None:
    headers, raw = delivery(envelope("erp", "quote.sent"), publisher="eds")
    assert (await post(web, headers, raw))[0] == 401
    # издатель crm подписал событие, источником которого указан erp
    headers, raw = delivery(envelope("erp", "quote.sent"), publisher="crm", secret=CRM_SECRET)
    assert (await post(web, headers, raw))[0] == 401


async def test_not_an_envelope_is_a_400(web: Web) -> None:
    headers, raw = delivery({"id": str(uuid.uuid4()), "hello": "world"})
    assert (await post(web, headers, raw))[0] == 400


async def test_redis_failure_is_a_503_and_the_retry_goes_through(web: Web) -> None:
    headers, raw = delivery(envelope("erp", "quote.sent"))
    web.redis.pubsub_down = True
    assert (await post(web, headers, raw))[0] == 503
    web.redis.pubsub_down = False
    status, body = await post(web, headers, raw)
    assert (status, body["status"]) == (200, "processed")
    assert len(hints(web)) == 1


async def test_without_a_pair_secret_nothing_is_accepted(
    web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RT_BUS_SECRET_ERP_PLATFORM_BFF")
    headers, raw = delivery(envelope("erp", "quote.sent"))
    assert (await post(web, headers, raw))[0] == 401


async def test_receiver_is_not_in_the_public_api_prefix(web: Web) -> None:
    headers, raw = delivery(envelope("erp", "quote.sent"))
    response = await web.client.post("/api/v1/bus/v1/events", content=raw, headers=headers)
    assert response.status_code == 404


async def test_bot_dialog_message_hints_only_the_conversation(web: Web) -> None:
    """D1-1: сообщение в диалоге с ботом (`handoff = false`) — только тема `messages`."""
    body = envelope("crm", "lead.message_added")
    body["data"] = {**body["data"], "handoff": False}
    headers, raw = delivery(body, publisher="crm", secret=CRM_SECRET)
    status, _ = await post(web, headers, raw)
    assert status == 200
    assert hints(web) == [
        {"topics": ["messages"], "reason": "uz.railtech.crm.lead.message_added.v1"}
    ]
