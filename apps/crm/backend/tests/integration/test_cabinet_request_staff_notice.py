"""СЦ-9: заявка клиента из кабинета — колокольчик и Telegram менеджеру, а не только директору.

Получатель: менеджер из события, иначе владелец клиента, иначе держатели `crm.clients: full`
(администратор карточку клиента открыть не может). Заявка не из кабинета сотруднику не пишется.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.auth import User
from app.models.clients import Client
from app.models.leads import LeadNote
from app.models.platform_roles import PlatformRole, UserPlatformRole
from app.models.staff_tickets import StaffNotification
from tests.bus_events import envelope_for
from tests.integration.bus_harness import (
    ERP_DEAL,
    T0,
    Harness,
    data_for,
    event_type_of,
)
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration

TEXT = "Заявка клиента ООО Порядок из кабинета · ждёт резолюции директора"


@pytest.fixture
def harness(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Harness]:
    stand = Harness(sessions)
    yield stand
    stand.close()


async def staff(
    sessions: async_sessionmaker[AsyncSession], email: str, tg: int, role: str | None = None
) -> int:
    account, _ = await make_user(sessions, email, ["viewer"])
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == account.id).values(tg_user_id=tg))
        if role is not None:
            found = (
                await session.scalars(select(PlatformRole).where(PlatformRole.code == role))
            ).one()
            session.add(UserPlatformRole(user_id=account.id, role_id=found.id))
    return account.id


async def own(sessions: async_sessionmaker[AsyncSession], client_id: int, user_id: int) -> None:
    async with sessions() as session, session.begin():
        client = await session.get(Client, client_id)
        assert client is not None
        client.owner_user_id = user_id


async def bell(sessions: async_sessionmaker[AsyncSession]) -> list[StaffNotification]:
    async with sessions() as session:
        return list(
            (
                await session.scalars(select(StaffNotification).order_by(StaffNotification.user_id))
            ).all()
        )


def cabinet_payload(**extra: object) -> dict[str, object]:
    return {"source": "cabinet", "erp_request_id": ERP_DEAL, "summary": "Оси колёсных пар", **extra}


async def test_event_manager_gets_the_bell_with_a_client_link_and_telegram(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    owner = await staff(sessions, "owner@x.uz", 9001)
    manager = await staff(sessions, "mgr@x.uz", 9002)
    await own(sessions, client_id, owner)
    event_id = await harness.store(
        "request.created", client_id, payload=cabinet_payload(manager_crm_user_id=manager)
    )

    assert await harness.process(event_id) == "processed"

    [note] = await bell(sessions)
    assert note.user_id == manager, "названный в событии менеджер, не владелец клиента"
    assert (note.kind, note.tab, note.title) == ("erp.cabinet_request", "clients", TEXT)
    assert (note.object_kind, note.object_id) == ("client", str(client_id))
    assert note.object_number == f"D-{ERP_DEAL}"
    assert note.subtitle == f"D-{ERP_DEAL} · Оси колёсных пар"
    assert harness.bot.sent == [(9002, TEXT)]


async def test_without_a_manager_the_client_owner_is_told(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    owner = await staff(sessions, "owner@x.uz", 9001)
    await own(sessions, client_id, owner)
    event_id = await harness.store("request.created", client_id, payload=cabinet_payload())

    assert await harness.process(event_id) == "processed"

    assert [n.user_id for n in await bell(sessions)] == [owner]
    assert harness.bot.sent == [(9001, TEXT)]


async def test_without_manager_and_owner_holders_of_clients_get_it_and_admins_do_not(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    holder = await staff(sessions, "mgr@x.uz", 9002, "tpl:MANAGER")
    await staff(sessions, "reader@x.uz", 9003, "tpl:ENGINEER")  # crm.clients: read — не адресат
    await staff(sessions, "admin@x.uz", 9004, "ADMIN")  # администратор карточку не откроет
    event_id = await harness.store("request.created", client_id, payload=cabinet_payload())

    assert await harness.process(event_id) == "processed"

    assert [n.user_id for n in await bell(sessions)] == [holder]
    assert harness.bot.sent == [(9002, TEXT)]


async def test_an_inactive_manager_falls_through_to_the_owner(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    owner = await staff(sessions, "owner@x.uz", 9001)
    gone = await staff(sessions, "gone@x.uz", 9002)
    await own(sessions, client_id, owner)
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == gone).values(is_active=False))
    event_id = await harness.store(
        "request.created", client_id, payload=cabinet_payload(manager_crm_user_id=gone)
    )

    assert await harness.process(event_id) == "processed"

    assert [n.user_id for n in await bell(sessions)] == [owner]


@pytest.mark.parametrize("source", ["erp", "crm"])
async def test_a_request_not_from_the_cabinet_does_not_write_to_staff(
    harness: Harness, sessions: async_sessionmaker[AsyncSession], source: str
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    owner = await staff(sessions, "owner@x.uz", 9001)
    await own(sessions, client_id, owner)
    event_id = await harness.store(
        "request.created",
        client_id,
        payload={"source": source, "erp_request_id": ERP_DEAL},
    )

    assert await harness.process(event_id) == "processed"

    assert await bell(sessions) == []
    assert harness.bot.sent == []


async def test_redelivery_does_not_duplicate_the_bell(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    client_id, _ = await harness.seed_client(tg_user_id=None)
    owner = await staff(sessions, "owner@x.uz", 9001)
    await own(sessions, client_id, owner)
    event_id = await harness.store("request.created", client_id, payload=cabinet_payload())
    assert await harness.process(event_id) == "processed"

    repeat = await harness.post(
        envelope_for(
            event_type_of("request.created"),
            data_for("request.created", client_id, payload=cabinet_payload()),
            time=T0,
            event_id=event_id,
        )
    )
    assert repeat.body["status"] == "duplicate"
    assert await harness.notices.deliver(event_id) == 0

    assert len(await bell(sessions)) == 1
    assert len(harness.bot.sent) == 1


async def test_lead_feed_names_the_request_and_quote_by_number_not_internal_id(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Лента лида: номер заявки из события, а не внутренний id ERP; КП — по номеру сделки."""
    client_id, _lead_id = await harness.seed_client(tg_user_id=None)
    await harness.process(
        await harness.store("request.created", client_id, payload=cabinet_payload())
    )
    await harness.process(await harness.store("quote.sent", client_id))

    async with sessions() as session:
        texts = (await session.scalars(select(LeadNote.text).order_by(LeadNote.id))).all()
    assert texts[0] == f"В бэк-офисе создана заявка D-{ERP_DEAL} (источник: cabinet)."
    assert texts[1].startswith(f"Клиенту отправлено КП по D-{ERP_DEAL}, версия 1")
    assert not any("#" in text for text in texts)


async def test_request_of_a_test_company_reaches_only_who_shows_test(
    harness: Harness, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """ТЕСТ-2: шлюз — колокольчик и Telegram по тестовому клиенту только при включённом показе."""
    client_id, _ = await harness.seed_client(tg_user_id=None)
    off = await staff(sessions, "off@x.uz", 9101, "tpl:MANAGER")
    on = await staff(sessions, "on@x.uz", 9102, "tpl:MANAGER")
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == on).values(show_test=True))
        await session.execute(update(Client).where(Client.id == client_id).values(is_test=True))
    event_id = await harness.store("request.created", client_id, payload=cabinet_payload())

    assert await harness.process(event_id) == "processed"

    assert [n.user_id for n in await bell(sessions)] == [on]
    assert harness.bot.sent == [(9102, TEXT)]
    assert off != on
