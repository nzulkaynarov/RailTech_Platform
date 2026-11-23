"""Проекция реквизитов компании ERP у клиента CRM (СУЩ-2.7, ADR-0028 п. 6) на реальном Postgres.

ERP публикует `uz.railtech.erp.company.updated.v1`; CRM принимает его приёмником с подписью пары
`erp → crm`, обработка — `process_inbox`. Проверяется: название, ИНН, страна и рег. номер клиента
со ссылкой меняются, сегмент и ответственный — нет, уходит `client.updated`; повтор — без
изменений; более старый снимок не откатывает новый; лишнее поле в `data` принимается; компания
без клиента — не ошибка. Правка названия и ИНН связанного клиента в CRM — 409.
"""

import copy
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError
from app.models.clients import Client
from app.security.principal import Principal
from app.services.clients import ClientService
from app.services.company_projection import COMPANY_UPDATED
from tests.bus_events import example_data
from tests.integration.bus_harness import ERP_COMPANY, Harness
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration


@pytest.fixture
async def harness(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[Harness]:
    h = Harness(sessions)
    yield h
    h.close()


def snapshot(at: str = "2026-11-18T09:00:00Z", **company: Any) -> dict[str, Any]:
    data = copy.deepcopy(example_data(COMPANY_UPDATED))
    data["erp_company_id"] = ERP_COMPANY
    data["company"].update({"updated_at": at, **company})
    return data


async def apply(harness: Harness, data: dict[str, Any]) -> None:
    event_id = await harness.receive(COMPANY_UPDATED, data)
    assert await harness.process(event_id) == "processed"


async def client_of(harness: Harness, client_id: int) -> Client:
    async with harness.sessions() as session:
        client = await session.get(Client, client_id)
        assert client is not None
        return client


async def client_updates(harness: Harness) -> list[dict[str, Any]]:
    async with harness.sessions() as session:
        rows = (
            await session.execute(
                text("SELECT envelope FROM rt_bus_outbox WHERE type = :t ORDER BY created_at, id"),
                {"t": "uz.railtech.crm.client.updated.v1"},
            )
        ).all()
    return [row[0]["data"] for row in rows]


async def test_the_snapshot_replaces_requisites_and_keeps_crm_fields(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    async with harness.sessions() as session, session.begin():
        client = await session.get(Client, client_id)
        assert client is not None
        client.segment = "Металлургия"

    await apply(
        harness,
        snapshot(name="АО «Новое имя»", inn="301234567", country="UZ", registration_number=None),
    )

    client = await client_of(harness, client_id)
    assert (client.name, client.inn, client.country, client.registration_number) == (
        "АО «Новое имя»",
        "301234567",
        "UZ",
        None,
    )
    assert client.segment == "Металлургия"
    [update] = await client_updates(harness)
    assert update["client"]["name"] == "АО «Новое имя»"


async def test_a_repeat_changes_nothing_and_an_older_snapshot_is_not_applied(
    harness: Harness,
) -> None:
    client_id, _ = await harness.seed_client()
    await apply(harness, snapshot(at="2026-11-18T10:00:00Z", name="Свежее"))
    await apply(harness, snapshot(at="2026-11-18T10:00:00Z", name="Свежее"))
    await apply(harness, snapshot(at="2026-11-18T09:00:00Z", name="Старое"))

    client = await client_of(harness, client_id)
    assert client.name == "Свежее"
    assert len(await client_updates(harness)) == 1


async def test_an_unknown_field_is_accepted_and_an_unlinked_company_is_not_an_error(
    harness: Harness,
) -> None:
    client_id, _ = await harness.seed_client()
    data = snapshot(name="С лишним полем")
    data["company"]["website"] = "https://example.uz"
    data["future_field"] = 1
    await apply(harness, data)
    assert (await client_of(harness, client_id)).name == "С лишним полем"

    other = snapshot(name="Чужая")
    other["erp_company_id"] = 999
    await apply(harness, other)
    async with harness.sessions() as session:
        names = (await session.scalars(select(Client.name))).all()
    assert "Чужая" not in names


async def test_name_and_inn_of_a_linked_client_are_not_edited_in_crm(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client()
    unlinked_id, _ = await harness.seed_client(erp_company_id=None, tg_user_id=None)
    account, _ = await make_user(sessions, "manager-req@example.com", ["manager"])
    who = Principal(user_id=account.id, full_name="Менеджер", roles=("manager",))
    service = ClientService(sessions)

    with pytest.raises(ConflictError) as refused:
        await service.update(who, client_id, {"name": "Своё имя"})
    assert refused.value.details["reason"] == "requisites_owned_by_erp"
    # то же значение и свои поля CRM — можно
    await service.update(who, client_id, {"name": "ООО Порядок", "segment": "Стройка"})
    assert (await client_of(harness, client_id)).segment == "Стройка"
    # клиент без компании ERP правится как раньше
    await service.update(who, unlinked_id, {"name": "Новое имя", "inn": "300000111"})
    assert (await client_of(harness, unlinked_id)).name == "Новое имя"


# --- Х-8: отметка «Не работать» едет в том же снимке ---------------------------------------


def mark(**fields: Any) -> dict[str, Any]:
    return {
        "reason": "Спор по оплате",
        "set_by": "Менеджер Демо",
        "set_at": "2026-11-18T09:00:00Z",
        "until": None,
        **fields,
    }


async def test_the_do_not_work_mark_is_projected_as_facts_and_cleared_by_null(
    harness: Harness,
) -> None:
    client_id, _ = await harness.seed_client()
    await apply(harness, snapshot(at="2026-11-18T10:00:00Z", do_not_work=mark()))
    client = await client_of(harness, client_id)
    assert client.do_not_work is not None
    assert (client.do_not_work["reason"], client.do_not_work["set_by"]) == (
        "Спор по оплате",
        "Менеджер Демо",
    )

    # снимок без поля (прежний издатель) отметку не трогает
    without = snapshot(at="2026-11-18T11:00:00Z", name="Без отметки в снимке")
    del without["company"]["do_not_work"]
    await apply(harness, without)
    assert (await client_of(harness, client_id)).do_not_work is not None

    # более старый снимок не снимает и не ставит отметку
    await apply(harness, snapshot(at="2026-11-18T08:00:00Z", do_not_work=None))
    assert (await client_of(harness, client_id)).do_not_work is not None

    await apply(harness, snapshot(at="2026-11-18T12:00:00Z", do_not_work=None))
    cleared = await client_of(harness, client_id)
    assert cleared.do_not_work is None
    assert cleared.do_not_work_reason is None


async def test_an_expired_mark_does_not_act(harness: Harness) -> None:
    client_id, _ = await harness.seed_client()
    await apply(harness, snapshot(do_not_work=mark(until="2020-01-01")))
    client = await client_of(harness, client_id)
    assert client.do_not_work_until is not None
    assert client.do_not_work is None
