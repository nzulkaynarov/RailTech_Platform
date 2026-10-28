"""Видимость документов не шире прав на вид (D1-10): один предикат для `/documents`, карточки, файла и реестра.

Чужой черновик видит только автор, исходящее письмо — только с `letters.read`, даже у держателя `registry.read`;
чужое — `404`, существование не раскрывается. Автор видит свой черновик и возвращённый документ, бухгалтер — служебки
к оплате, директор — всё, кроме чужих черновиков.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from app import clock
from app.container import Container
from app.models import ApprovalRoute, ApprovalStep
from tests.domain import Person
from tests.helpers import seed_employee
from tests.test_api_auth import assert_error
from tests.test_documents import WITH_AMOUNT, create, decide, submit
from tests.test_files import upload

pytestmark = pytest.mark.pg


@dataclass(frozen=True)
class Made:
    ids: dict[str, str]  # тема -> id документа
    files: dict[str, str]  # тема -> id файла


async def make(client: httpx.AsyncClient, staff: dict[str, Person]) -> Made:
    """Черновики письма и служебки с файлами, отправленное письмо с файлом, служебка к оплате, возвращённая служебка."""
    ids: dict[str, str] = {}
    files: dict[str, str] = {}

    async def new(who: str, subject: str, *, with_file: bool = False, **body: Any) -> dict[str, Any]:
        if with_file:
            ref = (await upload(client, staff[who])).json()
            files[subject] = ref["id"]
            body["file_ids"] = [ref["id"]]
        doc = await create(client, staff[who], subject=subject, **body)
        ids[subject] = doc["id"]
        return doc

    recipient = {"name": "ООО «Пример»"}
    await new("registrar", "Черновик письма", kind="letter_out", recipient=recipient, with_file=True)
    sent = await new("registrar", "Отправленное письмо", kind="letter_out", recipient=recipient, with_file=True)
    assert (await submit(client, staff["registrar"], sent["id"])).status_code == 200
    await new("manager", "Черновик служебки", with_file=True)
    to_pay = await new("manager", "Служебка к оплате", amount=WITH_AMOUNT["amount"], due_date=WITH_AMOUNT["due_date"])
    route = (await submit(client, staff["manager"], to_pay["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], route, "approve")).status_code == 200
    back = await new("supplier", "Возвращённая служебка")
    route = (await submit(client, staff["supplier"], back["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], route, "return", comment="Уточните")).status_code == 200
    return Made(ids, files)


async def subjects(client: httpx.AsyncClient, who: Person) -> list[str]:
    response = await client.get("/api/v1/documents", params={"limit": 100}, headers=who.headers)
    assert response.status_code == 200, response.text
    return sorted(i["subject"] for i in response.json()["items"])


NO_LETTERS = ["Возвращённая служебка", "Служебка к оплате"]


@pytest.mark.parametrize("who", ["supplier", "engineer"])
async def test_without_letters_read_no_outgoing_letters_and_no_foreign_drafts(
    client: httpx.AsyncClient, staff: dict[str, Person], who: str
) -> None:
    made = await make(client, staff)
    viewer = staff[who]
    # список: без писем и чужих черновиков (свой у снабженца — возвращённая служебка)
    assert await subjects(client, viewer) == NO_LETTERS
    # карточка: письма (черновик и отправленное) и чужой черновик — 404, служебки к оплате и возвращённая — 200
    for subject in ("Черновик письма", "Отправленное письмо", "Черновик служебки"):
        response = await client.get(f"/api/v1/documents/{made.ids[subject]}", headers=viewer.headers)
        assert_error(response, 404, "NOT_FOUND")
    for subject in NO_LETTERS:
        response = await client.get(f"/api/v1/documents/{made.ids[subject]}", headers=viewer.headers)
        assert response.status_code == 200, response.text
    # файл: так же, как документ (и содержимое, и версии)
    for file_id in made.files.values():
        for suffix in ("", "/versions"):
            assert_error(await client.get(f"/api/v1/files/{file_id}{suffix}", headers=viewer.headers), 404, "NOT_FOUND")
    # реестр опирается на тот же предикат
    registry = await client.get("/api/v1/registry", params={"limit": 100}, headers=viewer.headers)
    assert sorted(i["title"] for i in registry.json()["items"]) == NO_LETTERS


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        # автор видит свой черновик и возвращённое; письма — с `letters.read`
        ("manager", ["Возвращённая служебка", "Отправленное письмо", "Служебка к оплате", "Черновик служебки"]),
        # бухгалтер: служебка к оплате, письма читает, чужие черновики — нет
        ("accountant", ["Возвращённая служебка", "Отправленное письмо", "Служебка к оплате"]),
        # директор: всё, кроме чужих черновиков
        ("director", ["Возвращённая служебка", "Отправленное письмо", "Служебка к оплате"]),
        # регистратор (без registry.read): свои письма — оба, остальное не его
        ("registrar", ["Отправленное письмо", "Черновик письма"]),
    ],
)
async def test_holders_of_letters_read_see_letters_but_never_foreign_drafts(
    client: httpx.AsyncClient, staff: dict[str, Person], who: str, expected: list[str]
) -> None:
    made = await make(client, staff)
    viewer = staff[who]
    assert await subjects(client, viewer) == sorted(expected)
    for subject, doc_id in made.ids.items():
        response = await client.get(f"/api/v1/documents/{doc_id}", headers=viewer.headers)
        assert (response.status_code == 200) == (subject in expected), (who, subject)
    for subject, file_id in made.files.items():
        response = await client.get(f"/api/v1/files/{file_id}", headers=viewer.headers)
        assert (response.status_code == 200) == (subject in expected), (who, subject, "file")


async def test_author_keeps_own_draft_and_returned_document_without_registry_read(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    made = await make(client, staff)
    admin = staff["admin"]  # только memos.create: ни реестра, ни писем
    mine = await create(client, admin, subject="Админский черновик")
    assert await subjects(client, admin) == ["Админский черновик"]
    assert (await client.get(f"/api/v1/documents/{mine['id']}", headers=admin.headers)).status_code == 200
    for doc_id in made.ids.values():
        assert_error(await client.get(f"/api/v1/documents/{doc_id}", headers=admin.headers), 404, "NOT_FOUND")


async def sent_letter_route(client: httpx.AsyncClient, container: Container, staff: dict[str, Person]) -> str:
    """Маршрут, привязанный к исходящему письму. EDS сам таких маршрутов не создаёт (письмо уходит без согласования),
    поэтому строка пишется напрямую: предикат видимости не должен зависеть от того, кто и как создал маршрут."""
    letter = await create(
        client,
        staff["registrar"],
        kind="letter_out",
        subject="Письмо на согласовании",
        recipient={"name": "ООО «Пример»"},
    )
    assert (await submit(client, staff["registrar"], letter["id"])).status_code == 200
    route_id = uuid.uuid4()
    async with container.session_factory() as session, session.begin():
        session.add(
            ApprovalRoute(
                id=route_id,
                template="memo",
                title="Письмо на согласовании",
                status="open",
                round=1,
                current_step=1,
                document_id=uuid.UUID(letter["id"]),
                created_at=clock.now(),
            )
        )
        await session.flush()
        session.add(
            ApprovalStep(approval_id=route_id, index=1, label="Директор", assignee_crm_user_id=3, status="current")
        )
    return str(route_id)


async def route_ids(client: httpx.AsyncClient, who: Person) -> list[str]:
    response = await client.get("/api/v1/approvals", params={"limit": 100, "mine": 0}, headers=who.headers)
    assert response.status_code == 200, response.text
    return [i["id"] for i in response.json()["items"]]


@pytest.mark.parametrize("who", ["supplier", "engineer"])
async def test_route_of_outgoing_letter_is_hidden_without_letters_read(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], who: str
) -> None:
    """`registry.read` без `letters.read` и не участник: маршрута письма нет ни в списке, ни по id (404)."""
    approval_id = await sent_letter_route(client, container, staff)
    assert approval_id not in await route_ids(client, staff[who])
    assert_error(await client.get(f"/api/v1/approvals/{approval_id}", headers=staff[who].headers), 404, "NOT_FOUND")


@pytest.mark.parametrize("who", ["director", "accountant", "manager", "registrar"])
async def test_route_of_outgoing_letter_is_visible_to_participants_and_letter_readers(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], who: str
) -> None:
    """Директор (шаг маршрута), читатели писем с `registry.read` и автор-регистратор видят маршрут."""
    approval_id = await sent_letter_route(client, container, staff)
    assert approval_id in await route_ids(client, staff[who])
    assert (await client.get(f"/api/v1/approvals/{approval_id}", headers=staff[who].headers)).status_code == 200


async def test_participant_sees_route_even_without_letters_read(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    approval_id = await sent_letter_route(client, container, staff)
    # директор лишился `letters.read`, но шаг по-прежнему его: участник видит маршрут всегда
    await seed_employee(
        container,
        3,
        full_name="Рустам Директоров",
        email="user3@example.com",
        permissions={"eds": ["approvals.decide", "memos.approve", "registry.read"]},
    )
    director = staff["director"]
    assert approval_id in await route_ids(client, director)
    assert (await client.get(f"/api/v1/approvals/{approval_id}", headers=director.headers)).status_code == 200
    # а документ-письмо ему как не читателю писем не виден
    ids = (await client.get("/api/v1/documents", headers=director.headers)).json()["items"]
    assert all(i["kind"] != "letter_out" for i in ids)
