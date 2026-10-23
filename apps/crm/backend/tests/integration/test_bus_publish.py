"""Публикация событий CRM на шину rt_bus из сервисного слоя (B4, CONTRACTS §9).

Для каждого типа — вызов настоящего сервиса на настоящей БД и проверка строки outbox: тип, ключ
(`subject`), снимок `data` по схеме (шина проверяет её строго при записи). Отдельно: откат
транзакции — события нет; сбой публикации — изменение откатывается; вне транзакции — ошибка;
«грязные» телефоны, почта и длины не роняют изменение; раскладка по подписчикам из
`bus/subscriptions.yaml`; корреляция с `X-Request-ID` запроса.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from rt_bus import NotInTransactionError
from rt_bus.errors import EventValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import runtime
from app.bus.runtime import build_bus
from app.config import Settings
from app.main import create_app
from app.models.clients import Client, ClientContact
from app.models.leads import Lead, TelegramIdentity
from app.schemas.clients import ContactIn
from app.schemas.lead_intake import ManualLeadIn, WebLeadIn
from app.security.audit import Actor
from app.security.principal import Principal
from app.services import stages
from app.services.client_contacts import ClientContactService
from app.services.clients import ClientService
from app.services.lead_intake import LeadIntakeService
from app.services.lead_messenger import LeadMessenger
from app.services.leads import LeadService
from app.services.settings import SettingsService
from app.services.users import UserPatch, UserService
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration

ADMIN = Principal(user_id=1, full_name="Админ Админов", roles=("admin",))


@pytest.fixture
def bus(sessions: async_sessionmaker[AsyncSession]) -> Iterator[Any]:
    """Шина процесса для публикации; приёмник и очередь тут не нужны."""
    stand = build_bus(sessions, None)
    runtime.set_bus(stand)
    yield stand
    runtime.set_bus(None)


async def outbox(sessions: async_sessionmaker[AsyncSession]) -> list[dict[str, Any]]:
    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT type, subject, correlation_id, source, envelope "
                        "FROM rt_bus_outbox ORDER BY created_at, id"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def types(rows: list[dict[str, Any]]) -> list[str]:
    return [row["type"].removeprefix("uz.railtech.") for row in rows]


async def clear_outbox(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Подготовка данных тоже публикует события (создан сотрудник): проверяем только своё."""
    async with sessions() as session, session.begin():
        await session.execute(text("DELETE FROM rt_bus_outbox"))


async def admin_user(sessions: async_sessionmaker[AsyncSession]) -> Principal:
    account, _ = await make_user(sessions, "bus-admin@railtech.uz", ["admin"])
    await clear_outbox(sessions)
    return Principal(user_id=account.id, full_name="Админ Админов", roles=("admin",))


# ── Клиент ──────────────────────────────────────────────────────────────────────────────────────


async def test_client_created_and_updated(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)
    service = ClientService(sessions)

    client_id = await service.create(who, "ООО Рельс", "300000001", "rail")
    await service.update(who, client_id, {"name": "ООО Рельс-2", "segment": None})

    created, updated = await outbox(sessions)
    assert created["type"] == "uz.railtech.crm.client.created.v1"
    assert created["subject"] == f"client/{client_id}"
    assert created["source"] == "rt://crm"
    data = created["envelope"]["data"]
    assert data["actor"] == {"type": "staff", "crm_user_id": who.user_id}
    assert data["client"] == {
        "crm_client_id": client_id,
        "erp_company_id": None,
        "name": "ООО Рельс",
        "inn": "300000001",
        "segment": "rail",
        "is_active": True,
        "owner": {"crm_user_id": who.user_id, "full_name": "bus-admin"},
        "updated_at": data["client"]["updated_at"],
    }
    assert updated["type"] == "uz.railtech.crm.client.updated.v1"
    after = updated["envelope"]["data"]
    assert after["client"]["name"] == "ООО Рельс-2"
    assert after["client"]["segment"] is None
    assert after["changed_fields"] == ["name", "segment"]
    assert after["client"]["updated_at"] >= data["client"]["updated_at"]


async def test_client_update_that_changes_nothing_publishes_nothing(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)
    service = ClientService(sessions)
    client_id = await service.create(who, "ООО Рельс", None, None)

    await service.update(who, client_id, {"name": "ООО Рельс"})
    await service.update(who, client_id, {"notes": "заметка не входит в снимок"})

    assert types(await outbox(sessions)) == ["crm.client.created.v1"]


async def test_make_customer_with_a_new_client_publishes_client_and_lead_events(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)
    async with sessions() as session, session.begin():
        lead = Lead(display_name="Лид", stage="won", owner_mode="human")
        lead.assigned_user_id = who.user_id
        session.add(lead)
        await session.flush()
        lead_id = lead.id
    service = ClientService(sessions)

    client_id = await service.make_customer(who, lead_id, None, "ООО Новый")

    assert types(await outbox(sessions)) == [
        "crm.client.created.v1",
        "crm.lead.updated.v1",
        "crm.lead.stage_changed.v1",
    ]
    rows = await outbox(sessions)
    assert rows[1]["envelope"]["data"]["changed_fields"] == ["crm_client_id"]
    assert rows[1]["envelope"]["data"]["lead"]["crm_client_id"] == client_id
    stage_changed = rows[2]["envelope"]["data"]
    assert (stage_changed["from"], stage_changed["to"]) == ("won", "customer")


# ── Контакт ─────────────────────────────────────────────────────────────────────────────────────


async def test_contact_created_updated_deleted(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Контакты", erp_company_id=118)
        session.add(client)
        await session.flush()
        client_id = client.id
        identity = TelegramIdentity(
            tg_user_id=5150, client_id=client_id, verified_at=datetime.now(UTC)
        )
        session.add(identity)
        await session.flush()
        identity_id = identity.id
    service = ClientContactService(sessions)

    contact_id = await service.create(
        who,
        client_id,
        ContactIn(
            full_name="Иван Петров",
            position="Директор",
            phone="+998 90 123 45 67",
            email="Ivan@Rail.UZ",
            is_primary=True,
            telegram_identity_id=identity_id,
        ),
    )
    await service.update(
        who, client_id, contact_id, ContactIn(full_name="Иван П. Петров", is_primary=True)
    )
    await service.delete(who, client_id, contact_id)

    created, updated, deleted = await outbox(sessions)
    assert created["type"] == "uz.railtech.crm.contact.created.v1"
    assert created["subject"] == f"contact/{contact_id}"
    contact = created["envelope"]["data"]["contact"]
    assert contact == {
        "crm_contact_id": contact_id,
        "crm_client_id": client_id,
        "erp_company_id": 118,
        "full_name": "Иван Петров",
        "position": "Директор",
        "phone_e164": "+998901234567",
        "email": "ivan@rail.uz",
        "telegram_user_id": 5150,
        "is_primary": True,
        "updated_at": contact["updated_at"],
    }
    assert updated["type"] == "uz.railtech.crm.contact.updated.v1"
    assert updated["envelope"]["data"]["contact"]["phone_e164"] is None
    assert deleted["type"] == "uz.railtech.crm.contact.deleted.v1"
    gone = deleted["envelope"]["data"]
    assert (gone["crm_contact_id"], gone["crm_client_id"], gone["erp_company_id"]) == (
        contact_id,
        client_id,
        118,
    )
    assert gone["deleted_at"] >= updated["envelope"]["data"]["contact"]["updated_at"], (
        "поздний contact.updated не воскресит контакт: deleted_at не раньше updated_at"
    )


async def test_dirty_stored_values_are_normalised_and_never_break_the_change(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """Старые данные в БД («грязный» телефон, почта без домена, пустое имя, длинные строки) не
    должны ронять изменение: строгая проверка издателя видит уже нормализованный снимок."""
    who = await admin_user(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="  ", inn="9" * 32, segment="s" * 64)
        session.add(client)
        await session.flush()
        client_id = client.id
        contact = ClientContact(
            client_id=client_id,
            full_name="   ",
            position="п" * 255,
            phone_e164="8 (90) abc",
            email="not an email",
        )
        session.add(contact)
        await session.flush()
        contact_id = contact.id
    clients = ClientService(sessions)
    contacts = ClientContactService(sessions)

    await clients.update(who, client_id, {"is_active": False})
    await contacts.update(
        who, client_id, contact_id, ContactIn(full_name="Имя", email="OK@Rail.UZ")
    )
    async with sessions() as session, session.begin():
        row = await session.get(ClientContact, contact_id)
        assert row is not None
        row.phone_e164, row.email, row.full_name = "99890-123-45-67", "A@B", "   "
        await bus_events.contact_updated(session, row, Actor.system())

    updated_client, contact_ok, contact_dirty = await outbox(sessions)
    assert updated_client["envelope"]["data"]["client"]["name"] == "—"
    assert updated_client["envelope"]["data"]["client"]["is_active"] is False
    assert contact_ok["envelope"]["data"]["contact"]["email"] == "ok@rail.uz"
    dirty = contact_dirty["envelope"]["data"]["contact"]
    assert dirty["phone_e164"] == "+998901234567", "телефон приведён к E.164"
    assert dirty["email"] is None, "почта без домена не публикуется"
    assert dirty["full_name"] == "—"


# ── Лид ─────────────────────────────────────────────────────────────────────────────────────────


async def test_manual_lead_publishes_created_and_stage_changed(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)
    service = LeadIntakeService(sessions, SettingsService(sessions), b"form-key")

    lead_id = await service.create_manual(
        who,
        ManualLeadIn(source="phone", name="Алишер", company="ООО Рельс", phone="90 123 45 67"),
    )

    created, moved = await outbox(sessions)
    assert created["type"] == "uz.railtech.crm.lead.created.v1"
    assert created["subject"] == f"lead/{lead_id}"
    lead = created["envelope"]["data"]["lead"]
    assert (lead["stage"], lead["source"], lead["company_name"]) == ("new", "phone", "ООО Рельс")
    assert lead["assigned_user"] == {"crm_user_id": who.user_id, "full_name": "bus-admin"}
    assert {"phone_e164", "email"} & set(lead) == set(), "контакты лида в событие не попадают"
    assert "998901234567" not in str(created["envelope"])
    assert moved["type"] == "uz.railtech.crm.lead.stage_changed.v1"
    change = moved["envelope"]["data"]
    assert (change["from"], change["to"], change["reason"]) == (
        "new",
        "in_progress",
        "created_manually",
    )
    assert change["actor"] == {"type": "staff", "crm_user_id": who.user_id}


async def test_web_lead_is_created_by_the_system(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from datetime import timedelta

    from app.domain.web_form import issue_form_token

    key = b"form-key"
    service = LeadIntakeService(sessions, SettingsService(sessions), key)
    token = issue_form_token(key, datetime.now(UTC) - timedelta(seconds=30))

    lead_id = await service.create_web(
        WebLeadIn(
            name="Азиз",
            phone="90 111 22 33",
            text="Нужна интеграция",
            form_token=token,
            consent=True,
        ),
        "1.2.3.4",
    )

    (created,) = await outbox(sessions)
    assert created["type"] == "uz.railtech.crm.lead.created.v1"
    data = created["envelope"]["data"]
    assert data["actor"] == {"type": "system"}
    assert (data["lead"]["crm_lead_id"], data["lead"]["source"]) == (lead_id, "web")


async def test_taking_a_lead_publishes_the_stage_change_and_the_new_owner(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)
    async with sessions() as session, session.begin():
        lead = Lead(display_name="Лид", stage="handoff", owner_mode="paused", score=40)
        session.add(lead)
        await session.flush()
        lead_id = lead.id
    service = LeadService(sessions, SettingsService(sessions), LeadMessenger(sessions, None))

    await service.take(who, lead_id)

    moved, assigned = await outbox(sessions)
    assert moved["type"] == "uz.railtech.crm.lead.stage_changed.v1"
    assert moved["envelope"]["data"]["lead"]["score"] == 40
    assert assigned["type"] == "uz.railtech.crm.lead.updated.v1"
    data = assigned["envelope"]["data"]
    assert data["changed_fields"] == ["assigned_user"]
    assert data["lead"]["assigned_user"]["crm_user_id"] == who.user_id


async def test_stage_transitions_by_the_bot_and_timers_carry_the_right_actor(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from app.domain.stages import Stage, TransitionSource

    async with sessions() as session, session.begin():
        lead = Lead(display_name="Лид", stage="new")
        session.add(lead)
        await session.flush()
        await stages.transition(
            session, lead, Stage.ENGAGED, TransitionSource.QUALIFIER, reason="qualifier: ask"
        )
        await stages.transition(
            session, lead, Stage.UNRESPONSIVE, TransitionSource.TIMER, reason="no answer"
        )
        # переход в ту же стадию и запрещённый переход событий не дают
        await stages.transition(
            session, lead, Stage.UNRESPONSIVE, TransitionSource.TIMER, reason="again"
        )

    first, second = await outbox(sessions)
    assert first["envelope"]["data"]["actor"] == {"type": "bot"}
    assert second["envelope"]["data"]["actor"] == {"type": "system"}
    assert [
        (r["envelope"]["data"]["from"], r["envelope"]["data"]["to"]) for r in (first, second)
    ] == [("new", "engaged"), ("engaged", "unresponsive")]


async def test_sandbox_dialogs_are_not_published(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from app.domain.stages import Stage, TransitionSource

    async with sessions() as session, session.begin():
        lead = Lead(display_name="Тест админа", stage="new", source="sandbox")
        session.add(lead)
        await session.flush()
        await bus_events.lead_created(session, lead, Actor.system())
        await stages.transition(
            session, lead, Stage.ENGAGED, TransitionSource.QUALIFIER, reason="sandbox"
        )

    assert await outbox(sessions) == []


async def test_handoff_publishes_the_company_mapping_the_request_and_the_primary_contact(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    from tests.integration.bus_harness import Harness
    from tests.integration.test_erp_events import _handoff

    stand = Harness(sessions)
    try:
        client_id, lead_id = await stand.seed_client(erp_company_id=None)
        assert await _handoff(stand, client_id, lead_id) == "done"
    finally:
        stand.close()

    rows = await outbox(sessions)
    assert types(rows) == ["crm.contact.created.v1", "crm.client.updated.v1", "crm.lead.updated.v1"]
    client_event = rows[1]["envelope"]["data"]
    assert client_event["changed_fields"] == ["erp_company_id"]
    assert client_event["client"]["erp_company_id"] == 202
    assert client_event["actor"] == {"type": "system"}
    lead_event = rows[2]["envelope"]["data"]
    assert lead_event["lead"]["erp_request_id"] == 9001


# ── Сотрудник ───────────────────────────────────────────────────────────────────────────────────


async def test_user_created_updated_deactivated(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    admin = Actor(1, "user")
    service = UserService(sessions)

    view, _ = await service.create(
        admin, "New.Person@Railtech.uz", "Новый Сотрудник", ["manager"], position="Менеджер"
    )
    await service.update(admin, view.id, UserPatch(full_name="Новый С. Сотрудник"))
    await service.set_language(admin, view.id, "uz")
    await service.update(admin, view.id, UserPatch(is_active=False))

    created, updated, language, deactivated = await outbox(sessions)
    assert created["type"] == "uz.railtech.identity.user.created.v1"
    assert created["subject"] == f"user/{view.id}"
    user = created["envelope"]["data"]["user"]
    assert user == {
        "crm_user_id": view.id,
        "email": "new.person@railtech.uz",
        "full_name": "Новый Сотрудник",
        "position": "Менеджер",
        "language": "ru",
        "is_active": True,
        "platform_roles": [],
        "systems": ["crm"],
        "erp_role_codes": [],
        "updated_at": user["updated_at"],
    }
    assert "password" not in str(created["envelope"]), "секретов в событии нет"
    assert updated["envelope"]["data"]["user"]["full_name"] == "Новый С. Сотрудник"
    assert language["envelope"]["data"]["changed_fields"] == ["language"]
    assert language["envelope"]["data"]["user"]["language"] == "uz"
    assert deactivated["type"] == "uz.railtech.identity.user.deactivated.v1"
    assert deactivated["envelope"]["data"] == {
        "crm_user_id": view.id,
        "actor": {"type": "staff", "crm_user_id": 1},
    }


async def test_first_admin_is_published_as_a_created_user(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    service = UserService(sessions)

    user_id = await service.create_first_admin(
        "first@railtech.uz", "Первый Админ", PASSWORD, Actor.system()
    )
    again = await service.bootstrap_admin("first@railtech.uz", "Первый Админ", PASSWORD)

    assert again == PASSWORD
    created, restored = await outbox(sessions)
    assert created["type"] == "uz.railtech.identity.user.created.v1"
    assert created["envelope"]["data"]["user"]["crm_user_id"] == user_id
    assert created["envelope"]["data"]["user"]["platform_roles"] == ["ADMIN"]
    assert created["envelope"]["data"]["user"]["systems"] == ["crm", "erp"]
    assert restored["type"] == "uz.railtech.identity.user.updated.v1"


# ── Транзакционность ────────────────────────────────────────────────────────────────────────────


async def test_a_rolled_back_change_leaves_no_event(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)

    class BoomError(Exception):
        pass

    async def change_and_fail() -> None:
        async with sessions() as session, session.begin():
            client = Client(name="Откатится", owner_user_id=who.user_id)
            session.add(client)
            await session.flush()
            await bus_events.client_created(session, client, who.actor)
            raise BoomError

    with pytest.raises(BoomError):
        await change_and_fail()

    assert await outbox(sessions) == []
    async with sessions() as session:
        assert (await session.scalars(select(Client))).all() == []


async def test_a_publish_failure_rolls_the_change_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await admin_user(sessions)

    class BrokenBus:
        async def publish(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("bus is down")

    runtime.set_bus(BrokenBus())  # type: ignore[arg-type]
    try:
        with pytest.raises(RuntimeError, match="bus is down"):
            await ClientService(sessions).create(who, "Не создастся", None, None)
        with pytest.raises(RuntimeError, match="bus is down"):
            await UserService(sessions).create(
                Actor(who.user_id, "user"), "ghost@railtech.uz", "Призрак", ["viewer"]
            )
    finally:
        runtime.set_bus(None)

    async with sessions() as session:
        assert (await session.scalars(select(Client))).all() == []
        emails = (await session.execute(text("SELECT email FROM users"))).scalars().all()
    assert "ghost@railtech.uz" not in emails


async def test_publishing_outside_a_transaction_is_an_error(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    async with sessions() as session:
        client = Client(id=1, name="Вне транзакции")
        with pytest.raises(NotInTransactionError):
            await bus_events.client_created(session, client, Actor.system())
    assert await outbox(sessions) == []


async def test_an_event_that_does_not_fit_the_schema_is_refused_before_the_write(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    async with sessions() as session, session.begin():
        with pytest.raises(EventValidationError):
            await bus.publish(session, "uz.railtech.crm.client.updated.v1", {"client": {}})
    assert await outbox(sessions) == []


# ── Правки по ревью ─────────────────────────────────────────────────────────────────────────────


async def test_handing_over_the_work_publishes_an_event_for_every_lead_and_client(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    admin, _ = await make_user(sessions, "handover-admin@railtech.uz", ["admin"])
    leaving, _ = await make_user(sessions, "leaving@railtech.uz", ["manager"])
    colleague, _ = await make_user(sessions, "colleague@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        leads = [
            Lead(display_name=f"Лид {n}", stage="in_progress", owner_mode="human") for n in range(2)
        ]
        for lead in leads:
            lead.assigned_user_id = leaving.id
        clients = [Client(name=f"ООО {n}", owner_user_id=leaving.id) for n in range(2)]
        session.add_all([*leads, *clients])
        await session.flush()
        lead_ids = sorted(lead.id for lead in leads)
        client_ids = sorted(client.id for client in clients)
    await clear_outbox(sessions)

    await UserService(sessions).update(
        Actor(admin.id, "user"),
        leaving.id,
        UserPatch(is_active=False, transfer_to_user_id=colleague.id),
    )

    rows = await outbox(sessions)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append(row["envelope"]["data"])
    lead_events = by_type["uz.railtech.crm.lead.updated.v1"]
    client_events = by_type["uz.railtech.crm.client.updated.v1"]
    assert sorted(d["lead"]["crm_lead_id"] for d in lead_events) == lead_ids
    assert {d["lead"]["assigned_user"]["crm_user_id"] for d in lead_events} == {colleague.id}
    assert sorted(d["client"]["crm_client_id"] for d in client_events) == client_ids
    assert {d["client"]["owner"]["crm_user_id"] for d in client_events} == {colleague.id}
    assert by_type["uz.railtech.identity.user.deactivated.v1"][0]["crm_user_id"] == leaving.id


async def test_a_publish_failure_rolls_back_a_contact_and_a_lead(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await admin_user(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Откат")
        session.add(client)
        await session.flush()
        client_id = client.id

    class BrokenBus:
        async def publish(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("bus is down")

    runtime.set_bus(BrokenBus())  # type: ignore[arg-type]
    try:
        with pytest.raises(RuntimeError, match="bus is down"):
            await ClientContactService(sessions).create(
                who, client_id, ContactIn(full_name="Не создастся")
            )
        with pytest.raises(RuntimeError, match="bus is down"):
            await LeadIntakeService(sessions, SettingsService(sessions), b"k").create_manual(
                who, ManualLeadIn(source="phone", name="Не создастся", phone="+998901112233")
            )
    finally:
        runtime.set_bus(None)

    async with sessions() as session:
        assert (await session.scalars(select(ClientContact))).all() == []
        assert (await session.scalars(select(Lead))).all() == []


async def test_free_text_of_a_stage_reason_never_reaches_the_outbox(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)
    async with sessions() as session, session.begin():
        lead = Lead(display_name="Лид", stage="in_progress", owner_mode="human")
        lead.assigned_user_id = who.user_id
        session.add(lead)
        await session.flush()
        lead_id = lead.id
    secret_text = "Клиент просил перезвонить на +998901234567, ИНН 300000001"

    await LeadService(sessions, SettingsService(sessions), LeadMessenger(sessions, None)).close(
        who, lead_id, "lost", secret_text
    )

    rows = await outbox(sessions)
    assert "uz.railtech.crm.lead.stage_changed.v1" in [r["type"] for r in rows]
    assert "перезвонить" not in str([r["envelope"] for r in rows])
    stage_changed = next(r for r in rows if r["type"].endswith("lead.stage_changed.v1"))
    assert "reason" not in stage_changed["envelope"]["data"], "свободный текст — без кода причины"


@pytest.mark.parametrize(
    ("source", "reason", "code"),
    [
        ("user", "taken by manager", "taken_by_manager"),
        ("user", "won", "closed_won"),
        ("qualifier", "qualifier: ask_budget", "qualifier"),
        ("timer", "no reply for 5 days", "no_reply"),
        ("trigger", "price_or_contract_asked, human_requested", "escalation_trigger"),
        ("user", "Позвонить завтра", None),
        ("user", "", None),
    ],
)
def test_stage_reason_codes(source: str, reason: str, code: str | None) -> None:
    from app.bus.reasons import reason_code

    assert reason_code(source, reason) == code


async def test_contacts_that_lose_the_primary_flag_are_published_too(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    who = await admin_user(sessions)
    async with sessions() as session, session.begin():
        client = Client(name="ООО Основной")
        session.add(client)
        await session.flush()
        client_id = client.id
    service = ClientContactService(sessions)
    first = await service.create(who, client_id, ContactIn(full_name="Первый", is_primary=True))
    await clear_outbox(sessions)

    second = await service.create(who, client_id, ContactIn(full_name="Второй", is_primary=True))
    rows = await outbox(sessions)
    assert [(r["type"], r["subject"]) for r in rows] == [
        ("uz.railtech.crm.contact.created.v1", f"contact/{second}"),
        ("uz.railtech.crm.contact.updated.v1", f"contact/{first}"),
    ]
    assert rows[1]["envelope"]["data"]["contact"]["is_primary"] is False

    await clear_outbox(sessions)
    await service.update(who, client_id, first, ContactIn(full_name="Первый", is_primary=True))
    rows = await outbox(sessions)
    assert [(r["type"], r["subject"]) for r in rows] == [
        ("uz.railtech.crm.contact.updated.v1", f"contact/{first}"),
        ("uz.railtech.crm.contact.updated.v1", f"contact/{second}"),
    ]
    assert rows[1]["envelope"]["data"]["contact"]["is_primary"] is False


# ── Подписчики и корреляция ─────────────────────────────────────────────────────────────────────


async def test_events_are_laid_out_only_for_the_subscribers_of_the_file(
    sessions: async_sessionmaker[AsyncSession], bus: Any
) -> None:
    """ERP подписан на client.updated и contact.*;
    сотрудники и лиды — platform-bff; клиент-создан — пока никому.
    """
    who = await admin_user(sessions)
    clients = ClientService(sessions)
    client_id = await clients.create(who, "ООО Раскладка", None, None)
    await clients.update(who, client_id, {"inn": "123456789"})
    await ClientContactService(sessions).create(
        who, client_id, ContactIn(full_name="Контакт", is_primary=True)
    )
    await UserService(sessions).create(Actor.system(), "u@railtech.uz", "Сотрудник", ["viewer"])

    assert await bus.relay() == 4
    async with sessions() as session:
        rows = (
            await session.execute(
                text("SELECT event_type, subscriber FROM rt_bus_delivery ORDER BY id")
            )
        ).all()
    assert [(t.removeprefix("uz.railtech."), s) for t, s in rows] == [
        ("crm.client.updated.v1", "erp"),
        ("crm.contact.created.v1", "erp"),
        ("identity.user.created.v1", "platform-bff"),
    ]


@pytest.fixture
def api(live_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def test_the_request_id_becomes_the_correlation_id_of_the_event(
    sessions: async_sessionmaker[AsyncSession], api: TestClient
) -> None:
    account, password = await make_user(sessions, "corr-admin@railtech.uz", ["admin"])
    auth = login(api, account.email, password)
    await clear_outbox(sessions)

    named = api.post(
        "/api/v1/clients",
        json={"name": "ООО Корреляция"},
        headers={**auth, "X-Request-ID": "req-from-caddy-0001"},
    )
    anonymous = api.post("/api/v1/clients", json={"name": "ООО Без id"}, headers=auth)

    assert named.status_code == anonymous.status_code == 201
    first, second = await outbox(sessions)
    assert first["correlation_id"] == "req-from-caddy-0001"
    assert first["envelope"]["correlationid"] == "req-from-caddy-0001"
    assert named.headers["X-Request-ID"] == "req-from-caddy-0001"
    generated = anonymous.headers["X-Request-ID"]
    assert second["correlation_id"] == generated
    uuid.UUID(generated)  # не пришёл — сгенерирован UUID


async def test_the_traceparent_of_the_request_goes_into_the_event(
    sessions: async_sessionmaker[AsyncSession], api: TestClient
) -> None:
    account, password = await make_user(sessions, "trace-admin@railtech.uz", ["admin"])
    auth = login(api, account.email, password)
    await clear_outbox(sessions)
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    api.post(
        "/api/v1/clients",
        json={"name": "ООО Трасса"},
        headers={**auth, "traceparent": traceparent},
    )

    (row,) = await outbox(sessions)
    assert row["envelope"]["traceparent"] == traceparent
