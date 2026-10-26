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
    # C1-G-7: отправитель (компания, ИНН, контакт) и менеджер — из payload заявки
    assert letter["sender"] == {"name": "ООО «Пример Логистик»", "inn": "301234567", "contact": "Бахтиёр Каримов"}
    assert letter["manager"] == {"crm_user_id": 5, "full_name": "Алия Каримова"}
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
    assert event["data"]["letter"]["sender"] == {
        "name": "ООО «Пример Логистик»",
        "inn": "301234567",
        "contact": "Бахтиёр Каримов",
    }


async def test_old_event_without_sender_and_manager_is_still_accepted(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """L8: поля C1-G-7 необязательные — событие издателя до 2026-10-26 даёт письмо без отправителя и менеджера."""
    envelope = example("erp/request.created.v1")
    for name in ("company_name", "company_inn", "contact_name", "manager_crm_user_id"):
        del envelope["data"]["payload"][name]
    assert await deliver_erp(client, container, envelope) == "processed"
    [item] = (await client.get("/api/v1/letters", headers=staff["manager"].headers)).json()["items"]
    letter = (await client.get(f"/api/v1/letters/{item['id']}", headers=staff["manager"].headers)).json()
    validate("Letter", letter)
    assert letter["sender"] == {"name": None, "inn": None, "contact": None}
    assert letter["manager"] is None
    [event] = await outbox(container, "letter.registered")
    assert event["data"]["letter"]["sender"] == {"name": None, "inn": None}


async def test_long_company_name_is_cut_to_the_column_and_blank_contact_is_dropped(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Название компании ERP — до 300 символов, отправитель письма EDS — до 255; пустой контакт — нет контакта."""
    await deliver_erp(client, container, request_created(company_name="  " + "Я" * 298, contact_name=" "))
    [item] = (await client.get("/api/v1/letters", headers=staff["manager"].headers)).json()["items"]
    letter = (await client.get(f"/api/v1/letters/{item['id']}", headers=staff["manager"].headers)).json()
    validate("Letter", letter)
    assert letter["sender"] == {"name": "Я" * 255, "inn": "301234567", "contact": None}
