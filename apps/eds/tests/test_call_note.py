"""Записка о звонке (СЦ-6): рендер в воркере, файл сотрудника, идемпотентность, права, подпись на трёх языках (pg)."""

import re
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.container import Container
from app.models import DocumentRender, StoredFile
from app.services import call_note, renders
from app.services.call_note import TEXT
from app.services.storage import TEST_STORAGE
from app.tasks.renders import on_render_finished
from tests.domain import Person, deliver_erp, validate
from tests.test_api_auth import assert_error
from tests.test_erp_events import _letter, request_created
from tests.test_letterhead_letters import PDF, StubRenderer, deliver_letterhead

pytestmark = pytest.mark.pg

URL = "/api/v1/call-notes"
CALL = {
    "request_key": "form-key-0001",
    "lead": "L-0001",
    "caller_name": "Нигора Саидова",
    "company": "ООО «Восток Рейл»",
    "phone": "+998901234567",
    "email": "nigora@example.com",
    "called_at": "2026-11-20T09:30:00+00:00",
    "taken_by": "Алия Каримова",
    "need": "Нужен расчёт на 20 вагонов.\nСрок — до пятницы.",
    "lang": "ru",
}


@pytest.fixture
def deferred(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Хеши, которые API поставило бы в очередь после коммита."""
    found: list[str] = []

    async def record(self: Container, hashes: list[str]) -> None:
        found.extend(hashes)

    monkeypatch.setattr(Container, "defer_render", record)
    return found


async def work(container: Container, stub: StubRenderer, render_hash: str) -> str | None:
    """Задача воркера: те же хуки итога, что в `render_pdf` (`app/tasks/renders.py`)."""
    return await renders.run(
        container.session_factory,
        TEST_STORAGE,
        stub,
        render_hash,
        on_finished=on_render_finished(container),
    )


async def order(client: httpx.AsyncClient, who: Person, **changes: Any) -> httpx.Response:
    return await client.post(URL, json={**CALL, **changes}, headers=who.headers)


def cells(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Строки таблицы записки как пары «подпись — значение»."""
    table = next(n for n in payload["body"]["doc"]["content"] if n["type"] == "table")
    return [
        (row["content"][0]["content"][0]["content"][0]["text"], row["content"][1]["content"][0]["content"][0]["text"])
        for row in table["content"]
    ]


def paragraphs(payload: dict[str, Any]) -> list[str]:
    return [
        n["content"][0]["text"]
        for n in payload["body"]["doc"]["content"]
        if n["type"] == "paragraph" and n.get("content")
    ]


async def test_order_needs_the_letterhead(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    refused = await order(client, staff["manager"])
    assert_error(refused, 409, "CONFLICT")
    assert refused.json()["details"]["reason"] == "letterhead_missing"


async def test_note_is_rendered_in_the_worker_and_becomes_the_callers_file(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    manager = staff["manager"]
    await deliver_letterhead(client, container)
    ordered = await order(client, manager)
    assert ordered.status_code == 202, ordered.text
    validate("CallNote", ordered.json())
    assert (ordered.json()["status"], ordered.json()["file"]) == ("pending", None)
    assert len(deferred) == 1, "рендер ставится в очередь, а не строится в запросе"
    pending = await client.get(f"{URL}/{ordered.json()['id']}", headers=manager.headers)
    assert (pending.status_code, pending.json()["status"]) == (200, "pending")

    stub = StubRenderer()
    assert await work(container, stub, deferred[0]) == "ready"
    [payload] = stub.calls
    assert payload["layout"] == "internal" and "draft" not in payload, "макет internal, итоговый — без «ПРОЕКТ»"
    assert cells(payload) == [
        ("Кто звонил", "Нигора Саидова"),
        ("Компания", "ООО «Восток Рейл»"),
        ("Телефон", "+998901234567"),
        ("Почта", "nigora@example.com"),
    ]
    assert payload["meta"]["kind_label"] == "Записка о звонке", "вид документа — в инфоблоке листа, не заголовком тела"
    assert [(r["label"], r["value"]) for r in payload["meta"]["info"]] == [
        ("Когда", "20.11.2026 14:30"),
        ("Принял", "Алия Каримова"),
        ("Лид", "L-0001"),
    ]
    assert paragraphs(payload) == [
        "Что просил",
        "Нужен расчёт на 20 вагонов.",
        "Срок — до пятницы.",
        "Составлена системой по лиду L-0001",
    ]

    ready = await client.get(f"{URL}/{ordered.json()['id']}", headers=manager.headers)
    validate("CallNote", ready.json())
    ref = ready.json()["file"]
    assert (ready.json()["status"], ref["id"], ref["name"], ref["content_type"]) == (
        "ready",
        ordered.json()["id"],
        "Записка о звонке L-0001.pdf",
        "application/pdf",
    )
    assert ref["uploaded_by"]["crm_user_id"] == manager.id
    got = await client.get(f"/api/v1/files/{ref['id']}", headers=manager.headers)
    assert (got.status_code, got.content) == (200, PDF)


async def test_same_key_gives_the_same_file_and_renders_once(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    manager = staff["manager"]
    await deliver_letterhead(client, container)
    first = await order(client, manager)
    again = await order(client, manager)  # форму открыли повторно, пока записка строится
    assert first.json()["id"] == again.json()["id"]
    stub = StubRenderer()
    assert await work(container, stub, deferred[0]) == "ready"
    after = await order(client, manager)  # и после готовности
    assert (after.json()["id"], after.json()["status"]) == (first.json()["id"], "ready")
    assert after.json()["file"]["id"] == first.json()["id"]
    assert len(stub.calls) == 1 and len(deferred) == 2 and len(set(deferred)) == 1
    async with container.session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(StoredFile))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(DocumentRender))).scalar_one() == 1
    other_key = await order(client, manager, request_key="form-key-0002")
    assert other_key.json()["id"] != first.json()["id"], "новый ключ — новая записка"


async def test_note_belongs_to_its_author_only(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    await deliver_letterhead(client, container)
    mine = await order(client, staff["manager"])
    theirs = await order(client, staff["director"])  # тот же ключ у другого сотрудника — другой файл
    assert mine.json()["id"] != theirs.json()["id"]
    stub = StubRenderer()
    for render_hash in dict.fromkeys(deferred):
        assert await work(container, stub, render_hash) == "ready"
    note = mine.json()["id"]
    for path in (f"{URL}/{note}", f"/api/v1/files/{note}"):
        assert_error(await client.get(path, headers=staff["director"].headers), 404, "NOT_FOUND")
    assert (await client.get(f"{URL}/{note}", headers=staff["manager"].headers)).status_code == 200
    # пока строится, чужая записка тоже не видна
    pending = await order(client, staff["manager"], request_key="form-key-0003")
    assert_error(await client.get(f"{URL}/{pending.json()['id']}", headers=staff["director"].headers), 404, "NOT_FOUND")
    assert_error(
        await client.get(f"{URL}/{'0' * 8}-0000-0000-0000-{'0' * 12}", headers=staff["manager"].headers),
        404,
        "NOT_FOUND",
    )


async def test_note_is_attached_to_the_request_letter_of_its_author(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    """Файл записки принимает `files.attach` при регистрации письма по заявке (владелец файла — менеджер заявки)."""
    await deliver_letterhead(client, container)
    ordered = await order(client, staff["manager"])
    assert await work(container, StubRenderer(), deferred[0]) == "ready"
    assert await deliver_erp(client, container, request_created(letter_file_id=ordered.json()["id"])) == "processed"
    letter = await _letter(client, staff)
    assert [(f["id"], f["name"]) for f in letter["files"]] == [(ordered.json()["id"], "Записка о звонке L-0001.pdf")]
    assert "file.attached" in [e["action"] for e in letter["journal"]]


async def test_call_without_a_lead_has_its_own_name_and_footnote(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    await deliver_letterhead(client, container)
    ordered = await order(client, staff["manager"], lead=None, taken_by=None, company=None, phone=None, email=None)
    stub = StubRenderer()
    assert await work(container, stub, deferred[0]) == "ready"
    [payload] = stub.calls
    assert [label for label, _ in cells(payload)] == ["Кто звонил"]
    info = {row["label"]: row["value"] for row in payload["meta"]["info"]}
    assert list(info) == ["Когда", "Принял"] and info["Принял"] == "Алия Каримова", "без `taken_by` — сам сотрудник"
    assert paragraphs(payload)[-1] == "Составлена системой по звонку"
    ref = (await client.get(f"{URL}/{ordered.json()['id']}", headers=staff["manager"].headers)).json()["file"]
    assert ref["name"] == "Записка о звонке 2026-11-20.pdf"


async def test_note_of_a_non_phone_lead_carries_the_message_and_attachments(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    """One rule for every channel: the same note, titled as a request note, with the original message and file names."""
    await deliver_letterhead(client, container)
    ordered = await order(
        client,
        staff["manager"],
        channel="telegram",
        message="Нужны рельсы Р65.\nСрочно.",
        attachments=["ТЗ.pdf", "схема.png"],
    )
    assert ordered.status_code == 202, ordered.text
    stub = StubRenderer()
    assert await work(container, stub, deferred[0]) == "ready"
    [payload] = stub.calls
    assert dict(cells(payload))["Канал"] == "Telegram"
    # Nobody called: the requisite is "Клиент", never "Кто звонил".
    assert "Кто звонил" not in dict(cells(payload))
    assert dict(cells(payload))["Клиент"]
    assert payload["meta"]["kind_label"] == "Записка о запросе", "вид документа — в инфоблоке листа (ДОК-5)"
    assert paragraphs(payload) == [
        "Что просил",
        "Нужен расчёт на 20 вагонов.",
        "Срок — до пятницы.",
        "Исходное сообщение",
        "Нужны рельсы Р65.",
        "Срочно.",
        "Вложения",
        "ТЗ.pdf",
        "схема.png",
        "Составлена системой по лиду L-0001",
    ]
    ref = (await client.get(f"{URL}/{ordered.json()['id']}", headers=staff["manager"].headers)).json()["file"]
    assert ref["name"] == "Записка о запросе L-0001.pdf"


async def test_failed_render_is_reported_and_repeated_by_the_same_request(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    manager = staff["manager"]
    await deliver_letterhead(client, container)
    ordered = await order(client, manager)
    assert await work(container, StubRenderer(fail="failed"), deferred[0]) == "failed"
    failed = (await client.get(f"{URL}/{ordered.json()['id']}", headers=manager.headers)).json()
    assert (failed["status"], failed["file"]) == ("failed", None) and failed["error"]
    retry = await order(client, manager)
    assert retry.json()["status"] == "pending" and len(deferred) == 2
    assert await work(container, StubRenderer(), deferred[-1]) == "ready"
    assert (await client.get(f"{URL}/{ordered.json()['id']}", headers=manager.headers)).json()["status"] == "ready"


async def test_new_order_after_failure_is_pending_not_the_old_error(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    manager = staff["manager"]
    await deliver_letterhead(client, container)
    ordered = await order(client, manager)
    assert await work(container, StubRenderer(fail="failed"), deferred[0]) == "failed"
    again = await order(client, manager, need="Другое содержимое.")
    assert again.status_code == 202 and again.json()["id"] == ordered.json()["id"]
    assert len(deferred) == 2 and deferred[1] != deferred[0], "другое содержимое — новый хеш рендера"
    pending = (await client.get(f"{URL}/{ordered.json()['id']}", headers=manager.headers)).json()
    assert (pending["status"], pending["error"]) == ("pending", None)
    assert await work(container, StubRenderer(), deferred[1]) == "ready"
    ready = (await client.get(f"{URL}/{ordered.json()['id']}", headers=manager.headers)).json()
    assert (ready["status"], ready["file"] is not None) == ("ready", True)


async def test_request_is_validated_and_needs_a_permission(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await deliver_letterhead(client, container)
    assert (await order(client, staff["manager"], caller_name="")).status_code == 422
    assert (await order(client, staff["manager"], request_key="short")).status_code == 422
    assert (await order(client, staff["manager"], lang="de")).status_code == 422
    assert (await order(client, staff["manager"], extra="x")).status_code == 422
    assert (await client.post(URL, json=CALL)).status_code == 401
    assert (await order(client, staff["nobody"])).status_code == 403
    assert (await client.get(f"{URL}/{call_note.note_id('x', 1)}", headers=staff["nobody"].headers)).status_code == 403


def test_uzbek_note_is_new_latin_and_all_languages_have_the_same_labels() -> None:
    assert set(TEXT["ru"]) == set(TEXT["en"]) == set(TEXT["uz"])
    uz = " ".join(TEXT["uz"].values())
    assert not re.search(r"[ʻʼ'`’]|oʻ|gʻ|sh|ch|[А-Яа-я]", uz.replace("tomonidan", "")), "старые диграфы и кириллица"
    assert TEXT["uz"]["title"] == "Qönğiroq haqida yozuv" and "ngğ" not in uz.lower()
    assert "ö" in uz and "ğ" in uz and "ç" in uz, "новый алфавит: Ö Ğ Ş Ç"
