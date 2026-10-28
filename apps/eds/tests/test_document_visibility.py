"""Видимость документов не шире прав на вид (D1-10): один предикат для `/documents`, карточки, файла и реестра.

Чужой черновик видит только автор, исходящее письмо — только с `letters.read`, даже у держателя `registry.read`;
чужое — `404`, существование не раскрывается. Автор видит свой черновик и возвращённый документ, бухгалтер — служебки
к оплате, директор — всё, кроме чужих черновиков.
"""

from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from tests.domain import Person
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
