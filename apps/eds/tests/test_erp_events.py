"""Обработчик `erp.request.created` (pg): письмо по заявке, ВХ-номер, идемпотентность, дальнейшая резолюция."""

from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from tests.domain import Person, deliver_erp, outbox, validate
from tests.helpers import example

pytestmark = pytest.mark.pg


async def letters_count(container: Container) -> int:
    async with container.session_factory() as session:
        return int((await session.execute(text("SELECT count(*) FROM letters"))).scalar_one())


def request_created(**payload: Any) -> dict[str, Any]:
    envelope = example("erp/request.created.v1")
    envelope["data"]["payload"].update(payload)
    return envelope


async def test_request_created_registers_letter_with_links_and_event(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    assert await deliver_erp(client, container, request_created()) == "processed"
    page = (await client.get("/api/v1/letters", headers=staff["manager"].headers)).json()
    [item] = page["items"]
    letter = (await client.get(f"/api/v1/letters/{item['id']}", headers=staff["manager"].headers)).json()
    validate("Letter", letter)
    assert (letter["number"], letter["status"]) == ("ВХ-001/26", "awaiting_resolution")
    assert letter["subject"] == "Поставка оборудования, партия 1"
    assert letter["summary"] == "Нужны 20 комплектов, срок — ноябрь"
    assert letter["sender"] == {"name": None, "inn": None}
    assert letter["registered_by"] is None and letter["urgent"] is False
    assert letter["links"] == {
        "erp_request_id": 77,
        "erp_deal_id": 905,
        "deal_number": "D-2026-0905",
        "crm_client_id": 42,
        "erp_company_id": 118,
    }
    assert [e["action"] for e in letter["journal"]] == ["letter.registered"]
    assert letter["journal"][0]["by"] is None

    [event] = await outbox(container, "letter.registered")
    assert event["data"]["actor"] == {"type": "system"}
    assert event["data"]["links"]["erp_request_id"] == 77 and event["data"]["links"]["crm_client_id"] == 42
    assert event["data"]["letter"]["sender"] == {"name": None, "inn": None}


async def test_repeat_of_the_event_does_not_create_second_letter_or_number(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    first = request_created()
    await deliver_erp(client, container, first)
    # тот же event id: приёмник гасит повтор (inbox)
    assert await deliver_erp(client, container, first) == "processed"
    # другой event id, та же заявка ERP: обработчик находит прежнее письмо
    second = request_created()
    second["id"] = "5b5c595e-07aa-5bc9-aada-b84a0b3bd946"
    assert await deliver_erp(client, container, second) == "processed"
    assert await letters_count(container) == 1
    assert len(await outbox(container, "letter.registered")) == 1

    # следующее письмо получает следующий номер: прежний номер не «сгорел» и не повторён
    registered = await client.post(
        "/api/v1/letters",
        json={"subject": "Другое", "summary": "Суть", "sender": {"name": "ООО «Другое»"}, "received_at": "2026-10-26"},
        headers=staff["registrar"].headers,
    )
    assert registered.json()["number"] == "ВХ-002/26"


async def test_event_without_request_id_is_deduplicated_by_deal(
    client: httpx.AsyncClient, container: Container
) -> None:
    envelope = example("erp/request.created.v1")
    del envelope["data"]["payload"]["erp_request_id"]
    await deliver_erp(client, container, envelope)
    second = example("erp/request.created.v1")
    del second["data"]["payload"]["erp_request_id"]
    await deliver_erp(client, container, second)
    assert await letters_count(container) == 1


async def test_two_requests_make_two_letters_and_director_can_resolve_with_links(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, request_created())
    other = request_created(erp_request_id=78, summary="")
    other["data"]["deal"].update({"erp_deal_id": 906, "number": "D-2026-0906", "title": ""})
    await deliver_erp(client, container, other)
    page = (await client.get("/api/v1/letters", headers=staff["director"].headers)).json()
    assert [i["number"] for i in page["items"]] == ["ВХ-002/26", "ВХ-001/26"]
    assert page["items"][0]["subject"] == "Заявка D-2026-0906"  # у заявки нет темы — по номеру сделки

    resolved = await client.post(
        f"/api/v1/letters/{page['items'][1]['id']}/resolution",
        json={
            "text": "Считать",
            "assignees": [{"crm_user_id": 11, "zone": "goods"}],
            "due": "2026-10-30",
            "min_margin_pct": "15",
        },
        headers=staff["director"].headers,
    )
    assert resolved.status_code == 200
    [event] = await outbox(container, "letter.resolved")
    assert event["data"]["links"]["erp_request_id"] == 77 and event["data"]["links"]["erp_deal_id"] == 905
    assert event["data"]["letter"]["number"] == "ВХ-001/26"
