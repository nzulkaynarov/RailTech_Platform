"""Партнёр ERP становится клиентом CRM (PART-CRM) на реальном Postgres и приёмнике шины.

ERP публикует `uz.railtech.erp.partner.client_requested.v1`; CRM принимает его приёмником с
подписью пары `erp → crm`, обработка — `process_inbox`. Проверяется: создание клиента и контактов;
найденный по ИНН или паре «страна + рег. номер» существующий клиент НЕ привязывается сам (ответ
`pending_confirmation`, ни `erp_company_id`, ни контактов партнёра у чужого клиента), решение
менеджера («Это та же компания» / «Нет — завести нового»); нормализация ключей; неактивные клиенты
не ищутся; повтор (тем же событием и новым); конфликт сопоставления; отказ ERP снимает привязку;
откат обработки; параллельные запросы (детерминированно); терпимость к лишним полям.
"""

import asyncio
import copy
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.bus import runtime
from app.domain.errors import ConflictError, NotFoundError
from app.models.auth import AuditLog
from app.models.clients import Client, ClientContact, PartnerClientRequest
from app.models.staff_tickets import StaffNotification
from app.security.principal import Principal
from app.services import partner_clients
from app.services.partner_clients import REJECTED_TYPE, REQUESTED_TYPE, PartnerClientService
from tests.bus_events import envelope_for, example_data
from tests.integration.bus_harness import FakeContainer, Harness
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration

RESOLVED_TYPE = "uz.railtech.crm.partner.client_resolved.v1"
ERP_COMPANY = 214


class PartnerContainer(FakeContainer):
    def __init__(self, harness: Harness) -> None:
        super().__init__(harness.service, harness.bus)
        self.partner_clients = PartnerClientService(harness.sessions)


class Stand:
    def __init__(self, harness: Harness) -> None:
        self.h = harness
        runtime.install(cast(Any, PartnerContainer(harness)))

    async def request(self, data: dict[str, Any], *, event_id: str | None = None) -> str:
        """Принять запрос ERP приёмником шины и обработать его."""
        event_id = await self.h.receive(REQUESTED_TYPE, data, event_id=event_id)
        assert await self.h.process(event_id) == "processed"
        return event_id

    async def requests(self) -> list[PartnerClientRequest]:
        async with self.h.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(PartnerClientRequest).order_by(PartnerClientRequest.id)
                    )
                ).all()
            )

    async def clients(self) -> list[Client]:
        async with self.h.sessions() as session:
            return list((await session.scalars(select(Client).order_by(Client.id))).all())

    async def contacts(self) -> list[ClientContact]:
        async with self.h.sessions() as session:
            return list(
                (await session.scalars(select(ClientContact).order_by(ClientContact.id))).all()
            )

    async def outbox(self, event_type: str | None = None) -> list[dict[str, Any]]:
        async with self.h.sessions() as session:
            rows = (
                (
                    await session.execute(
                        text("SELECT type, envelope FROM rt_bus_outbox ORDER BY created_at, id")
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows if event_type is None or r["type"] == event_type]

    async def answers(self) -> list[dict[str, Any]]:
        return [row["envelope"]["data"] for row in await self.outbox(RESOLVED_TYPE)]

    async def audit(self, action: str) -> list[AuditLog]:
        async with self.h.sessions() as session:
            return list(
                (await session.scalars(select(AuditLog).where(AuditLog.action == action))).all()
            )

    async def bell(self) -> list[StaffNotification]:
        async with self.h.sessions() as session:
            return list(
                (
                    await session.scalars(select(StaffNotification).order_by(StaffNotification.id))
                ).all()
            )


@pytest.fixture
async def stand(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[Stand]:
    harness = Harness(sessions)
    yield Stand(harness)
    harness.close()


def request_data(**over: Any) -> dict[str, Any]:
    data = copy.deepcopy(example_data(REQUESTED_TYPE))
    data["erp_company_id"] = ERP_COMPANY
    data["invited_by_crm_user_id"] = None
    data.update(over)
    return data


def company(**over: Any) -> dict[str, Any]:
    return {**example_data(REQUESTED_TYPE)["company"], **over}


async def make_client(sessions: async_sessionmaker[AsyncSession], **fields: Any) -> int:
    async with sessions() as session, session.begin():
        client = Client(name=fields.pop("name", "Существующий клиент"), **fields)
        session.add(client)
        await session.flush()
        return client.id


async def make_contact(
    sessions: async_sessionmaker[AsyncSession], client_id: int, email: str, **fields: Any
) -> int:
    async with sessions() as session, session.begin():
        row = ClientContact(
            client_id=client_id,
            full_name=fields.pop("full_name", "Известный"),
            email=email,
            **fields,
        )
        session.add(row)
        await session.flush()
        return row.id


# ── Создание ──────────────────────────────────────────────────────────────────────────────────────


async def manager_of(stand: "Stand", email: str = "decider@x.uz") -> Principal:
    account, _ = await make_user(stand.h.sessions, email, ["manager"])
    return Principal(user_id=account.id, full_name="Менеджер", roles=("manager",))


async def test_new_company_becomes_a_client_with_contacts_and_an_answer(stand: Stand) -> None:
    manager, _ = await make_user(stand.h.sessions, "inviter@x.uz", ["manager"])

    await stand.request(request_data(invited_by_crm_user_id=manager.id))

    [client] = await stand.clients()
    assert (client.name, client.inn, client.erp_company_id) == (
        "Демо Мануфактуринг ООО",
        "301234567",
        ERP_COMPANY,
    )
    assert client.owner_user_id == manager.id, "ответственный — пригласивший сотрудник"
    assert client.erp_handoff_status == "done"
    assert client.notes is not None
    assert "Образцовая" in client.notes
    assert "manufacturing.example" in client.notes
    [contact] = await stand.contacts()
    assert (contact.client_id, contact.email, contact.is_primary) == (
        client.id,
        "ivanov@manufacturing.example",
        True,
    )
    assert contact.phone_e164 == "+998901234567"
    assert contact.preferred_channel == "email"
    [answer] = await stand.answers()
    assert answer == {
        "erp_company_id": ERP_COMPANY,
        "status": "linked",
        "crm_client_id": client.id,
        "matched_by": "created",
        "contacts": [{"erp_contact_id": 612, "crm_contact_id": contact.id}],
        "actor": {"type": "system"},
    }
    # штатные снимки клиента и контакта опубликованы с сопоставлением
    [created] = await stand.outbox("uz.railtech.crm.client.created.v1")
    assert created["envelope"]["data"]["client"]["erp_company_id"] == ERP_COMPANY
    [contact_event] = await stand.outbox("uz.railtech.crm.contact.created.v1")
    assert contact_event["envelope"]["data"]["contact"]["erp_company_id"] == ERP_COMPANY
    assert [row.kind for row in await stand.bell()] == ["partner_client_new"]
    assert [a.entity_id for a in await stand.audit("client.partner_linked")] == [str(client.id)]


async def test_without_a_crm_user_the_client_has_no_owner_and_admins_are_told(stand: Stand) -> None:
    admin, _ = await make_user(stand.h.sessions, "boss@x.uz", ["admin"])

    await stand.request(request_data(invited_by_crm_user_id=987_654))  # такого сотрудника в CRM нет

    [client] = await stand.clients()
    assert client.owner_user_id is None
    assert [(row.user_id, row.tab) for row in await stand.bell()] == [(admin.id, "clients")]


async def test_inactive_inviter_does_not_become_the_owner(stand: Stand) -> None:
    gone, _ = await make_user(stand.h.sessions, "gone@x.uz", ["manager"])
    async with stand.h.sessions() as session, session.begin():
        await session.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": gone.id}
        )

    await stand.request(request_data(invited_by_crm_user_id=gone.id))

    [client] = await stand.clients()
    assert client.owner_user_id is None


async def test_foreign_company_is_stored_by_country_and_registration_number(stand: Stand) -> None:
    foreign = company(inn=None, country="CN", registration_number="91310000MA1K")

    await stand.request(request_data(company=foreign))

    [client] = await stand.clients()
    assert (client.inn, client.country, client.registration_number) == (None, "CN", "91310000MA1K")


# ── Совпадение по ключу: не автопривязка ──────────────────────────────────────────────────────────


async def test_hostile_inn_of_a_foreign_client_changes_nothing_of_it(stand: Stand) -> None:
    """Партнёр указал ИНН чужого клиента: у того ни привязки, ни контактов партнёра, ни событий."""
    owner, _ = await make_user(stand.h.sessions, "owner2@x.uz", ["manager"])
    victim = await make_client(
        stand.h.sessions, name="Чужой клиент", inn="301234567", owner_user_id=owner.id
    )
    kept = await make_contact(stand.h.sessions, victim, "boss@victim.example", is_primary=True)
    async with stand.h.sessions() as session, session.begin():  # у клиента есть сделка
        await session.execute(
            text("INSERT INTO deals (client_id, title, stage) VALUES (:c, 'Сделка', 'open')"),
            {"c": victim},
        )

    await stand.request(request_data())

    [client] = await stand.clients()
    assert (client.id, client.erp_company_id, client.name) == (victim, None, "Чужой клиент")
    assert client.erp_handoff_status is None
    assert [c.id for c in await stand.contacts()] == [kept], "контактов партнёра у клиента нет"
    [answer] = await stand.answers()
    assert answer == {
        "erp_company_id": ERP_COMPANY,
        "status": "pending_confirmation",
        "crm_client_id": victim,
        "matched_by": "inn",
        "actor": {"type": "system"},
    }
    assert await stand.outbox("uz.railtech.crm.client.updated.v1") == []
    assert await stand.outbox("uz.railtech.crm.contact.created.v1") == []
    [pending] = await stand.requests()
    assert (pending.client_id, pending.status, pending.erp_company_id) == (
        victim,
        "pending",
        ERP_COMPANY,
    )
    [note] = await stand.bell()
    assert (note.user_id, note.kind, note.tab) == (owner.id, "partner_client_confirm", "clients")
    assert len(await stand.audit("client.partner_pending")) == 1
    assert await stand.audit("client.partner_linked") == []


async def test_pending_repeat_refreshes_the_request_and_does_not_notify_again(
    stand: Stand,
) -> None:
    await make_client(stand.h.sessions, inn="301234567")
    await make_user(stand.h.sessions, "boss3@x.uz", ["admin"])
    await stand.request(request_data())
    second = request_data()
    second["contacts"][0]["full_name"] = "Иванов Пётр Сергеевич"

    await stand.request(second)

    [pending] = await stand.requests()
    assert pending.payload["contacts"][0]["full_name"] == "Иванов Пётр Сергеевич"
    assert len(await stand.bell()) == 1
    assert [a["status"] for a in await stand.answers()] == ["pending_confirmation"] * 2


async def test_manager_confirms_and_the_client_is_linked(stand: Stand) -> None:
    manager = await manager_of(stand)
    client_id = await make_client(
        stand.h.sessions, name="Наше название", inn="301234567", segment="vip", notes="заметка"
    )
    known = await make_contact(
        stand.h.sessions, client_id, "Ivanov@Manufacturing.Example", is_primary=True
    )
    await make_user(stand.h.sessions, "boss4@x.uz", ["admin"])
    await stand.request(request_data())
    [pending] = await stand.requests()

    service = PartnerClientService(stand.h.sessions)
    await service.confirm(manager, client_id, pending.id)

    [client] = await stand.clients()
    assert client.id == client_id
    assert client.erp_company_id == ERP_COMPANY
    assert (client.name, client.segment, client.notes) == ("Наше название", "vip", "заметка")
    assert [c.id for c in await stand.contacts()] == [known], "контакт с тем же e-mail не задвоен"
    last = (await stand.answers())[-1]
    assert last["status"] == "linked"
    assert last["matched_by"] == "inn"
    assert last["contacts"] == [{"erp_contact_id": 612, "crm_contact_id": known}]
    [updated] = await stand.outbox("uz.railtech.crm.client.updated.v1")
    assert updated["envelope"]["data"]["changed_fields"] == ["erp_company_id"]
    [done] = await stand.requests()
    assert done.status == "confirmed"
    assert done.decided_by_user_id == manager.user_id
    assert len(await stand.audit("client.partner_linked")) == 1
    with pytest.raises(NotFoundError):  # повторное решение по той же заявке
        await service.confirm(manager, client_id, pending.id)


async def test_new_contact_of_a_confirmed_client_is_not_primary(stand: Stand) -> None:
    manager = await manager_of(stand)
    client_id = await make_client(stand.h.sessions, inn="301234567")
    primary = await make_contact(stand.h.sessions, client_id, "boss@old.example", is_primary=True)
    await stand.request(request_data())
    [pending] = await stand.requests()

    await PartnerClientService(stand.h.sessions).confirm(manager, client_id, pending.id)

    contacts = await stand.contacts()
    assert [(c.id, c.is_primary) for c in contacts] == [(primary, True), (contacts[1].id, False)]
    assert contacts[1].email == "ivanov@manufacturing.example"


async def test_manager_declines_and_a_new_client_is_made_for_the_partner(stand: Stand) -> None:
    manager = await manager_of(stand)
    other = await make_client(stand.h.sessions, name="Не та компания", inn="301234567")
    await stand.request(request_data())
    [pending] = await stand.requests()

    new_id = await PartnerClientService(stand.h.sessions).decline(manager, other, pending.id)

    clients = {c.id: c for c in await stand.clients()}
    assert clients[other].erp_company_id is None
    assert clients[other].name == "Не та компания"
    assert clients[new_id].erp_company_id == ERP_COMPANY
    assert [c.client_id for c in await stand.contacts()] == [new_id]
    last = (await stand.answers())[-1]
    assert (last["status"], last["crm_client_id"], last["matched_by"]) == (
        "linked",
        new_id,
        "created",
    )
    [done] = await stand.requests()
    assert done.status == "declined"


async def test_decision_on_a_foreign_or_decided_request_is_not_found(stand: Stand) -> None:
    manager = await manager_of(stand)
    client_id = await make_client(stand.h.sessions, inn="301234567")
    other = await make_client(stand.h.sessions, inn="300000111")
    await stand.request(request_data())
    [pending] = await stand.requests()
    service = PartnerClientService(stand.h.sessions)

    with pytest.raises(NotFoundError):
        await service.confirm(manager, other, pending.id)  # заявка другого клиента
    with pytest.raises(NotFoundError):
        await service.decline(manager, client_id, 999_999)
    assert (await stand.requests())[0].status == "pending"


async def test_confirm_is_refused_when_the_client_got_linked_to_another_company(
    stand: Stand,
) -> None:
    manager = await manager_of(stand)
    client_id = await make_client(stand.h.sessions, inn="301234567")
    await stand.request(request_data())
    [pending] = await stand.requests()
    async with stand.h.sessions() as session, session.begin():  # пока заявка ждала, клиента заняли
        await session.execute(
            text("UPDATE clients SET erp_company_id = 999 WHERE id = :id"), {"id": client_id}
        )

    with pytest.raises(ConflictError):
        await PartnerClientService(stand.h.sessions).confirm(manager, client_id, pending.id)

    assert (await stand.requests())[0].status == "pending"
    assert (await stand.clients())[0].erp_company_id == 999


async def test_foreign_company_by_the_pair_goes_to_confirmation_too(stand: Stand) -> None:
    same = await make_client(stand.h.sessions, country="CN", registration_number="abc-1")
    other_country = await make_client(stand.h.sessions, country="KZ", registration_number="ABC-1")

    await stand.request(
        request_data(company=company(inn=None, country="CN", registration_number="ABC 1"))
    )

    clients = {c.id: c for c in await stand.clients()}
    assert len(clients) == 2, "нового клиента не создано"
    assert clients[same].erp_company_id is None
    assert clients[other_country].erp_company_id is None
    [answer] = await stand.answers()
    assert (answer["status"], answer["crm_client_id"], answer["matched_by"]) == (
        "pending_confirmation",
        same,
        "registration_number",
    )


async def test_same_number_in_another_country_is_a_different_company(stand: Stand) -> None:
    await make_client(stand.h.sessions, country="KZ", registration_number="ABC-1")

    await stand.request(
        request_data(company=company(inn=None, country="CN", registration_number="ABC-1"))
    )

    assert len(await stand.clients()) == 2
    assert (await stand.answers())[0]["status"] == "linked"


@pytest.mark.parametrize(
    ("stored", "requested"),
    [
        ("301 234 567", "301234567"),
        ("301-234-567", "301234567"),
        ("301234567", "301.234.567"),
        ("0301234567", "0301234567"),
    ],
)
async def test_inn_is_compared_by_digits(stand: Stand, stored: str, requested: str) -> None:
    await make_client(stand.h.sessions, inn=stored)

    await stand.request(request_data(company=company(inn=requested)))

    assert (await stand.answers())[0]["status"] == "pending_confirmation"


async def test_leading_zeros_of_an_inn_are_kept(stand: Stand) -> None:
    await make_client(stand.h.sessions, inn="0301234567")

    await stand.request(request_data(company=company(inn="301234567")))

    assert (await stand.answers())[0]["status"] == "linked", "это другой ИНН"
    assert len(await stand.clients()) == 2


@pytest.mark.parametrize("requested", ["AB-12 34", "ab1234", "A B 1 2-3 4"])
async def test_registration_number_ignores_spaces_dashes_and_case(
    stand: Stand, requested: str
) -> None:
    await make_client(stand.h.sessions, country="CN", registration_number="ab 12-34")

    await stand.request(
        request_data(company=company(inn=None, country="CN", registration_number=requested))
    )

    assert (await stand.answers())[0]["status"] == "pending_confirmation"


async def test_inactive_client_is_not_searched_by_key(stand: Stand) -> None:
    await make_client(stand.h.sessions, inn="301234567", is_active=False)

    await stand.request(request_data())

    clients = await stand.clients()
    assert len(clients) == 2
    assert (await stand.answers())[0]["status"] == "linked"
    assert [c.erp_company_id for c in clients] == [None, ERP_COMPANY]


async def test_inn_wins_over_the_number_pair(stand: Stand) -> None:
    by_inn = await make_client(stand.h.sessions, inn="301234567")
    await make_client(stand.h.sessions, country="CN", registration_number="ABC-1")

    await stand.request(request_data(company=company(country="CN", registration_number="ABC-1")))

    [answer] = await stand.answers()
    assert answer["crm_client_id"] == by_inn
    assert answer["matched_by"] == "inn"


# ── Повтор ────────────────────────────────────────────────────────────────────────────────────────


async def test_the_same_event_twice_has_one_effect(stand: Stand) -> None:
    event_id = str(uuid.uuid4())
    data = request_data()

    await stand.request(data, event_id=event_id)
    redelivery = await stand.h.post(envelope_for(REQUESTED_TYPE, data, event_id=event_id))
    assert redelivery.status_code == 200
    await stand.h.process(event_id)

    assert len(await stand.clients()) == 1
    assert len(await stand.contacts()) == 1
    assert len(await stand.answers()) == 1


async def test_a_second_request_for_the_same_company_creates_nothing_new(stand: Stand) -> None:
    """ERP просит повторно, пока сопоставления нет: клиент и контакты те же, ответ повторяется."""
    await make_user(stand.h.sessions, "boss2@x.uz", ["admin"])
    await stand.request(request_data())
    await stand.request(request_data())

    assert len(await stand.clients()) == 1
    assert len(await stand.contacts()) == 1
    first, second = await stand.answers()
    assert first["crm_client_id"] == second["crm_client_id"]
    assert (first["matched_by"], second["matched_by"]) == ("created", "erp_company_id")
    assert len(await stand.outbox("uz.railtech.crm.client.created.v1")) == 1
    assert len(await stand.audit("client.partner_linked")) == 1, "журнал не задваивается"
    assert len(await stand.bell()) == 1


async def test_two_requests_for_one_company_at_once_make_one_client(
    stand: Stand, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Параллельная обработка: после поиска каждый обработчик «задумывается» 0,3 с. Без блокировки
    оба ничего не находят и создают по клиенту; с блокировкой второй ждёт первого — клиент один."""
    real_find = partner_clients._find

    async def slow_find(*args: Any, **kwargs: Any) -> Any:
        found = await real_find(*args, **kwargs)
        await asyncio.sleep(0.3)
        return found

    monkeypatch.setattr(partner_clients, "_find", slow_find)
    first = await stand.h.receive(REQUESTED_TYPE, request_data())
    second = await stand.h.receive(REQUESTED_TYPE, request_data())

    await asyncio.gather(stand.h.process(first), stand.h.process(second))

    assert len(await stand.clients()) == 1
    assert len(await stand.contacts()) == 1


async def test_a_new_contact_in_a_repeat_request_is_added_once(stand: Stand) -> None:
    await stand.request(request_data())
    second = request_data()
    second["contacts"].append(
        {
            "erp_contact_id": 613,
            "full_name": "Петров",
            "email": "Petrov@manufacturing.example",
            "phone": None,
            "language": "en",
        }
    )

    await stand.request(second)
    await stand.request(second)

    assert [c.email for c in await stand.contacts()] == [
        "ivanov@manufacturing.example",
        "petrov@manufacturing.example",
    ]


# ── Конфликт и отказ ERP ──────────────────────────────────────────────────────────────────────────


async def test_client_mapped_to_another_company_is_not_overwritten(stand: Stand) -> None:
    owner, _ = await make_user(stand.h.sessions, "owner@x.uz", ["manager"])
    client_id = await make_client(
        stand.h.sessions,
        name="Занятый клиент",
        inn="301234567",
        erp_company_id=999,
        owner_user_id=owner.id,
    )

    await stand.request(request_data())

    [client] = await stand.clients()
    assert (client.id, client.erp_company_id, client.name) == (client_id, 999, "Занятый клиент")
    assert await stand.contacts() == [], "контакты чужому клиенту не добавляются"
    [answer] = await stand.answers()
    assert answer == {
        "erp_company_id": ERP_COMPANY,
        "status": "conflict",
        "crm_client_id": client_id,
        "conflict_erp_company_id": 999,
        "actor": {"type": "system"},
    }
    [entry] = await stand.audit("client.partner_conflict")
    assert entry.after is not None
    assert entry.after["existing_erp_company_id"] == 999
    [note] = await stand.bell()
    assert (note.user_id, note.kind, note.tab) == (owner.id, "partner_client_conflict", "clients")
    assert "объедин" not in (note.subtitle or "").lower()
    assert await stand.outbox("uz.railtech.crm.client.updated.v1") == []
    assert await stand.audit("client.partner_linked") == []


async def test_conflict_by_registration_number_pair(stand: Stand) -> None:
    await make_client(
        stand.h.sessions, country="CN", registration_number="ABC-1", erp_company_id=999
    )

    await stand.request(
        request_data(company=company(inn=None, country="CN", registration_number="abc-1"))
    )

    [answer] = await stand.answers()
    assert answer["status"] == "conflict"
    assert answer["conflict_erp_company_id"] == 999


async def test_erp_rejection_releases_the_link_and_tells_the_owner(stand: Stand) -> None:
    owner, _ = await make_user(stand.h.sessions, "owner5@x.uz", ["manager"])
    client_id = await make_client(
        stand.h.sessions, inn="301234567", erp_company_id=ERP_COMPANY, owner_user_id=owner.id
    )
    data = {
        "erp_company_id": ERP_COMPANY,
        "crm_client_id": client_id,
        "reason": "client_mapped_to_other_company",
        "other_erp_company_id": 301,
        "actor": {"type": "system"},
    }

    event_id = await stand.h.receive(REJECTED_TYPE, data)
    assert await stand.h.process(event_id) == "processed"

    [client] = await stand.clients()
    assert client.erp_company_id is None
    assert client.erp_handoff_status is None
    [updated] = await stand.outbox("uz.railtech.crm.client.updated.v1")
    assert updated["envelope"]["data"]["client"]["erp_company_id"] is None
    assert len(await stand.audit("client.partner_released")) == 1
    [note] = await stand.bell()
    assert (note.user_id, note.kind) == (owner.id, "partner_client_released")


async def test_erp_rejection_of_a_link_the_client_does_not_hold_changes_nothing(
    stand: Stand,
) -> None:
    client_id = await make_client(stand.h.sessions, inn="301234567", erp_company_id=555)
    data = {
        "erp_company_id": ERP_COMPANY,
        "crm_client_id": client_id,
        "reason": "client_mapped_to_other_company",
        "other_erp_company_id": None,
        "actor": {"type": "system"},
    }

    event_id = await stand.h.receive(REJECTED_TYPE, data)
    assert await stand.h.process(event_id) == "processed"

    assert (await stand.clients())[0].erp_company_id == 555
    assert await stand.audit("client.partner_released") == []


# ── Откат и терпимость ────────────────────────────────────────────────────────────────────────────


async def test_failed_processing_leaves_nothing(
    stand: Stand, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("сбой публикации ответа")

    monkeypatch.setattr(bus_events, "partner_client_resolved", broken)
    event_id = await stand.h.receive(REQUESTED_TYPE, request_data())
    assert await stand.h.process(event_id) != "processed"

    assert await stand.clients() == []
    assert await stand.contacts() == []
    assert await stand.outbox() == []
    assert await stand.bell() == []


async def test_unknown_fields_are_tolerated(stand: Stand) -> None:
    data = request_data(future_field={"x": 1})
    data["company"]["future_company_field"] = 1

    await stand.request(data)

    assert len(await stand.clients()) == 1
