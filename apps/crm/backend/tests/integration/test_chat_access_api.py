"""Переписка с клиентами отдельно от реестра лидов (B-D18-1, W18A-P3) — матрица ролей на Postgres.

Правило — `app/domain/chat_access.py`: реестр лидов (очередь, список, карточка, решения) — только
`leads:*` (раздел `crm.leads`); `chats:*` (раздел `chats.external`) открывает переписку, вложения и
заметки только тех диалогов, где сотрудник участвует (ответственный за лида, клиента или сделку,
автор ответа), или назначенных его зоне (`chats:invoiced` от `eds.payments: full` — сделки клиента
со счётом). Чужой диалог держателю `chats:*` — 404; без обоих прав — 403 «not allowed».
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.clients import Client
from app.models.deals import Deal
from app.models.leads import Conversation, Lead
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services import message_log
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, escalated_lead, login, make_user

pytestmark = pytest.mark.integration

INVOICED_ERP_DEAL = 7301
FILE_KEY = "tg/chat-access/{lead}/act.pdf"


class StubStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def get(self, bucket: str, key: str) -> bytes:
        return self.files[key]


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        storage = StubStorage()
        test_client.app.state.container.__dict__["storage"] = storage  # type: ignore[attr-defined]
        test_client.storage = storage  # type: ignore[attr-defined]
        yield test_client


@dataclass
class World:
    """Лиды по отношению к сотруднику «переписка без реестра» (`chat`) и бухгалтеру."""

    assigned: int  # chat — ответственный за лида
    wrote: int  # chat ответил клиенту в этом диалоге
    client_owner: int  # chat — ответственный за клиента
    deal_owner: int  # chat — ответственный за сделку клиента
    invoiced: int  # по сделке клиента выставлен счёт; ведёт другой менеджер
    foreign: int  # чужой диалог без счёта
    headers: dict[str, dict[str, str]]


async def _lead_with_file(
    sessions: async_sessionmaker[AsyncSession], storage: StubStorage, tg_user_id: int
) -> int:
    lead_id = await escalated_lead(sessions, tg_user_id=tg_user_id)
    key = FILE_KEY.format(lead=lead_id)
    storage.files[key] = b"%PDF-1.4 act"
    async with sessions() as session, session.begin():
        conversation = (
            await session.scalars(select(Conversation).where(Conversation.lead_id == lead_id))
        ).one()
        await message_log.add(
            session,
            conversation,
            role="lead",
            text="Платёжка во вложении",
            attachments=[
                {
                    "kind": "file",
                    "name": "act.pdf",
                    "mime": "application/pdf",
                    "size": 12,
                    "storage_key": key,
                    "stored": True,
                }
            ],
        )
    return lead_id


async def _with_client(
    sessions: async_sessionmaker[AsyncSession], lead_id: int, **client_fields: Any
) -> int:
    async with sessions() as session, session.begin():
        row = Client(name=f"ООО Клиент {lead_id}", **client_fields)
        session.add(row)
        await session.flush()
        lead = await session.get(Lead, lead_id)
        assert lead is not None
        lead.client_id = row.id
        return row.id


async def _staff(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    boss: dict[str, str],
    email: str,
    access: dict[str, str] | None = None,
    code: str | None = None,
) -> tuple[int, dict[str, str]]:
    """Сотрудник с ролью каталога `code` или своей ролью с матрицей `access`."""
    account, _ = await make_user(sessions, email, ["viewer"])
    if code is not None:
        async with sessions() as session:
            (role,) = await prepo.by_codes(session, [code])
            role_id = role.id
    else:
        response = client.post(
            "/api/v1/platform-roles", json={"name": f"Роль {email}", "access": access}, headers=boss
        )
        assert response.status_code == 201, response.text
        role_id = int(response.json()["id"])
    await UserService(sessions).update(
        Actor.system(), account.id, UserPatch(platform_role_ids=[role_id])
    )
    return account.id, login(client, account.email, PASSWORD)


@pytest.fixture
async def world(client: TestClient, sessions: async_sessionmaker[AsyncSession]) -> World:
    storage: StubStorage = client.storage  # type: ignore[attr-defined]
    boss_account, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    boss = login(client, boss_account.email, PASSWORD)
    other, _ = await make_user(sessions, "other-manager@railtech.uz", ["manager"])
    headers: dict[str, dict[str, str]] = {}
    chat_id, headers["chat"] = await _staff(
        client, sessions, boss, "chat@railtech.uz", access={"chats.external": "full"}
    )
    _, headers["accountant"] = await _staff(
        client, sessions, boss, "accountant@railtech.uz", code="tpl:ACCOUNTANT"
    )
    _, headers["manager"] = await _staff(
        client, sessions, boss, "manager@railtech.uz", code="tpl:MANAGER"
    )
    _, headers["director"] = await _staff(
        client, sessions, boss, "director@railtech.uz", code="DIRECTOR"
    )
    _, headers["admin"] = await _staff(client, sessions, boss, "admin@railtech.uz", code="ADMIN")
    _, headers["supply"] = await _staff(
        client, sessions, boss, "supply@railtech.uz", code="tpl:SUPPLY"
    )
    _, headers["cashier"] = await _staff(
        client, sessions, boss, "cashier@railtech.uz", access={"eds.payments": "full"}
    )

    leads = [await _lead_with_file(sessions, storage, 8100 + n) for n in range(6)]
    assigned, wrote, client_owner, deal_owner, invoiced, foreign = leads
    async with sessions() as session, session.begin():
        for lead_id in leads:
            lead = await session.get(Lead, lead_id)
            assert lead is not None
            lead.assigned_user_id = chat_id if lead_id == assigned else other.id
            lead.owner_mode = "human"
        conversation = (
            await session.scalars(select(Conversation).where(Conversation.lead_id == wrote))
        ).one()
        await message_log.add(
            session, conversation, role="manager", text="Счёт отправили", sent_by_user_id=chat_id
        )
    await _with_client(sessions, client_owner, owner_user_id=chat_id)
    deal_client = await _with_client(sessions, deal_owner)
    invoiced_client = await _with_client(sessions, invoiced)
    async with sessions() as session, session.begin():
        session.add(Deal(client_id=deal_client, title="Сделка", owner_user_id=chat_id))
        session.add(
            Deal(
                client_id=invoiced_client,
                title="Поставка",
                erp_deal_id=INVOICED_ERP_DEAL,
                owner_user_id=other.id,
                invoice_issued_at=datetime(2026, 10, 20, tzinfo=UTC),
            )
        )
    return World(assigned, wrote, client_owner, deal_owner, invoiced, foreign, headers)


def _denied_by_right(response: Any) -> bool:
    body = response.json()
    return response.status_code == 403 and "is not allowed" in str(body.get("message"))


def _listed(client: TestClient, headers: dict[str, str], **params: Any) -> dict[int, str]:
    response = client.get("/api/v1/chats", params=params, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == len(body["items"])
    return {item["lead_id"]: item["access"] for item in body["items"]}


def _dialog_reads(lead_id: int, message_id: int) -> list[str]:
    return [
        f"/api/v1/leads/{lead_id}/messages",
        f"/api/v1/leads/{lead_id}/notes",
        f"/api/v1/leads/{lead_id}/messages/{message_id}/attachments/0",
    ]


def _file_message(client: TestClient, headers: dict[str, str], lead_id: int) -> int:
    messages = client.get(f"/api/v1/leads/{lead_id}/messages", headers=headers).json()
    return int(next(m["id"] for m in messages if m["attachments"]))


REGISTRY = [
    "/api/v1/inbox",
    "/api/v1/leads",
    "/api/v1/leads/{lead}",
    "/api/v1/leads/{lead}/decisions",
]


async def test_accountant_sees_only_invoiced_dialogs_and_no_lead_registry(
    client: TestClient, world: World
) -> None:
    accountant = world.headers["accountant"]
    for path in REGISTRY:
        response = client.get(path.format(lead=world.invoiced), headers=accountant)
        assert _denied_by_right(response), (path, response.status_code, response.text)

    assert _listed(client, accountant) == {world.invoiced: "invoiced"}
    assert _listed(client, accountant, erp_deal_id=INVOICED_ERP_DEAL) == {
        world.invoiced: "invoiced"
    }
    assert _listed(client, accountant, erp_deal_id=INVOICED_ERP_DEAL + 1) == {}

    message = _file_message(client, accountant, world.invoiced)
    for path in _dialog_reads(world.invoiced, message):
        assert client.get(path, headers=accountant).status_code == 200, path
    file = client.get(_dialog_reads(world.invoiced, message)[2], headers=accountant)
    assert file.content == b"%PDF-1.4 act"

    # Чужие диалоги без счёта — как несуществующие, файлы тоже.
    for lead_id in (world.foreign, world.assigned, world.client_owner):
        for path in _dialog_reads(lead_id, message):
            response = client.get(path, headers=accountant)
            assert response.status_code == 404, (lead_id, path, response.text)


async def test_accountant_writes_notes_but_replies_only_after_taking_the_lead(
    client: TestClient, world: World
) -> None:
    accountant = world.headers["accountant"]
    note = client.post(
        f"/api/v1/leads/{world.invoiced}/actions/note",
        json={"text": "Запросили платёжку"},
        headers=accountant,
    )
    assert note.status_code == 200, note.text
    foreign = client.post(
        f"/api/v1/leads/{world.foreign}/actions/note", json={"text": "x"}, headers=accountant
    )
    assert foreign.status_code == 404
    # Право на ответ есть, но лид ведёт менеджер: объектное правило сервиса, не отказ по праву.
    reply = client.post(
        f"/api/v1/leads/{world.invoiced}/messages",
        json={"text": "Пришлите платёжку"},
        headers=accountant,
    )
    assert reply.status_code in (403, 409), reply.text
    assert not _denied_by_right(reply), reply.text
    take = client.post(f"/api/v1/leads/{world.invoiced}/actions/take", headers=accountant)
    assert _denied_by_right(take)


async def test_chat_holder_without_registry_sees_own_dialogs_only(
    client: TestClient, world: World
) -> None:
    chat = world.headers["chat"]
    mine = {world.assigned, world.wrote, world.client_owner, world.deal_owner}
    assert _listed(client, chat) == dict.fromkeys(mine, "participant")
    for path in REGISTRY:
        response = client.get(path.format(lead=world.assigned), headers=chat)
        assert _denied_by_right(response), (path, response.status_code)
    message = _file_message(client, chat, world.assigned)
    for path in _dialog_reads(world.assigned, message):
        assert client.get(path, headers=chat).status_code == 200, path
    # Счёт выставлен, но зоны «Счета и оплаты» у роли нет; чужой — тоже 404.
    for lead_id in (world.invoiced, world.foreign):
        response = client.get(f"/api/v1/leads/{lead_id}/messages", headers=chat)
        assert response.status_code == 404, lead_id


async def test_sandbox_dialog_is_closed_to_chat_holders_even_when_assigned(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    """Песочница — не переписка с клиентом: ни в списке, ни по номеру (как `GET /chats`)."""
    async with sessions() as session, session.begin():
        lead = await session.get(Lead, world.assigned)
        assert lead is not None
        lead.source = "sandbox"
    chat = world.headers["chat"]
    assert world.assigned not in _listed(client, chat)
    response = client.get(f"/api/v1/leads/{world.assigned}/messages", headers=chat)
    assert response.status_code == 404


@pytest.mark.parametrize("who", ["manager", "director"])
async def test_lead_registry_holders_see_every_dialog(
    client: TestClient, world: World, who: str
) -> None:
    headers = world.headers[who]
    listed = _listed(client, headers)
    assert set(listed) >= {world.foreign, world.invoiced, world.assigned}
    assert set(listed.values()) == {"registry"}
    assert client.get("/api/v1/inbox", headers=headers).status_code == 200
    for lead_id in (world.foreign, world.invoiced):
        message = _file_message(client, headers, lead_id)
        for path in _dialog_reads(lead_id, message):
            assert client.get(path, headers=headers).status_code == 200, (who, path)


async def test_director_reads_dialogs_but_does_not_reply(client: TestClient, world: World) -> None:
    reply = client.post(
        f"/api/v1/leads/{world.foreign}/messages",
        json={"text": "x"},
        headers=world.headers["director"],
    )
    assert _denied_by_right(reply)


@pytest.mark.parametrize("who", ["admin", "supply", "cashier"])
async def test_roles_without_external_chats_get_no_dialogs(
    client: TestClient, world: World, who: str
) -> None:
    """Администратор, снабженец и роль только с «Счетами и оплатами»: зона без `chats.external`
    переписку не открывает — 403 по праву, а не 404."""
    headers = world.headers[who]
    assert _denied_by_right(client.get("/api/v1/chats", headers=headers))
    for path in [*REGISTRY, "/api/v1/leads/{lead}/messages", "/api/v1/leads/{lead}/notes"]:
        response = client.get(path.format(lead=world.invoiced), headers=headers)
        assert _denied_by_right(response), (who, path, response.status_code)
