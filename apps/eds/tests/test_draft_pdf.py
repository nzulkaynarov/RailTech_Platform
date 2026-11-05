"""«ПРОЕКТ» на неитоговом PDF письма и доступ к нему (SIGN-1, ADR-0024 п. 4; pg).

Любой PDF, который не итоговый (зарегистрированное письмо с номером и датой), строится с `draft: true` — рендер печатает
«ПРОЕКТ» на каждой странице без номера и даты; итоговый — без ключа, хеш выпущенных PDF не меняется. Проект открывают
автор и делопроизводитель переданного черновика; PDF без знака, построенный до SIGN-1, не выдаётся.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import update

from app.container import Container
from app.errors import EdsError
from app.models import Document, DocumentRender, Employee
from app.services import letter_mail, renders
from app.services.documents import may_open_pdf
from tests.domain import Person
from tests.test_api_auth import assert_error
from tests.test_letterhead_letters import (
    StubRenderer,
    deliver_letterhead,
    letter_json,
    run,
)

pytestmark = pytest.mark.pg


@pytest.fixture
def deferred(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Хеши, которые API поставило бы в очередь после коммита (как в `test_letterhead_letters`)."""
    found: list[str] = []

    async def record(self: Container, hashes: list[str]) -> None:
        found.extend(hashes)

    monkeypatch.setattr(Container, "defer_render", record)
    return found


FINAL_KEYS = {"renderer", "layout", "body", "meta", "letterhead", "logo_sha256"}  # ввод итогового — как до SIGN-1


async def draft_letter(client: httpx.AsyncClient, container: Container, author: Person) -> str:
    await deliver_letterhead(client, container)
    created = await client.post("/api/v1/documents", json=letter_json(), headers=author.headers)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def make_ready(
    client: httpx.AsyncClient, container: Container, deferred: list[str], who: Person, doc: str
) -> dict[str, Any]:
    posted = await client.post(f"/api/v1/documents/{doc}/pdf", headers=who.headers)
    assert posted.status_code == 202, posted.text
    stub = StubRenderer()
    assert await run(container, stub, deferred[-1]) == "ready"
    return stub.calls[0]


async def test_draft_render_is_marked_and_final_is_not(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    doc = await draft_letter(client, container, staff["manager"])
    payload = await make_ready(client, container, deferred, staff["manager"], doc)
    assert payload["draft"] is True and payload["meta"]["number"] is None
    row_status = (await client.get(f"/api/v1/documents/{doc}/pdf", headers=staff["manager"].headers)).json()
    assert row_status["final"] is False

    # передали на регистрацию → делопроизводитель регистрирует: итоговый PDF — без ключа `draft`, с номером
    assert (
        await client.post(f"/api/v1/documents/{doc}/registration-request", headers=staff["manager"].headers)
    ).status_code == 200
    registered = await client.post(f"/api/v1/documents/{doc}/submit", headers=staff["registrar"].headers)
    assert registered.status_code == 200, registered.text
    final_hash = deferred[-1]
    stub = StubRenderer()
    assert await run(container, stub, final_hash) == "ready"
    final = stub.calls[0]
    assert "draft" not in final and set(final) == FINAL_KEYS
    assert final["meta"]["number"] == registered.json()["number"] and final["meta"]["date"] is not None
    assert renders.digest(final) == final_hash  # хеш итогового — по прежнему вводу
    assert (await client.get(f"/api/v1/documents/{doc}/pdf", headers=staff["registrar"].headers)).json()["final"]


async def test_renderer_process_passes_draft_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """`render_payload` передаёт `draft` в rt-docs: проект — `draft=True`, итоговый — `False`."""
    import sys
    import types

    from app.services import render_process

    seen: list[bool] = []

    class Result:
        pdf, warnings = b"%PDF", ()
        stats = types.SimpleNamespace(pages=1, last_page_fill=0.1)

    def fake_render(body: Any, **kw: Any) -> Result:
        seen.append(kw["draft"])
        return Result()

    monkeypatch.setitem(sys.modules, "rt_docs.pdf", types.SimpleNamespace(render_pdf=fake_render))
    base: dict[str, Any] = {
        "layout": "letter",
        "body": {},
        "meta": {"number": None, "date": None, "addressee": [], "reply_to": None, "executor": None},
        "letterhead": {"company_name": "X", "requisites": [], "footer": [], "accent": "#15294d", "font": "sans"},
    }
    render_process.render_payload({**base, "draft": True}, None, None)
    render_process.render_payload(base, None, None)
    assert seen == [True, False]


async def test_draft_pdf_is_open_only_to_author_and_registrar_of_handed_over(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    doc = await draft_letter(client, container, staff["manager"])
    await make_ready(client, container, deferred, staff["manager"], doc)
    file_url = f"/api/v1/documents/{doc}/pdf/file"
    status_url = f"/api/v1/documents/{doc}/pdf"

    assert (await client.get(file_url, headers=staff["manager"].headers)).status_code == 200  # автор
    for who in ("registrar", "director", "accountant", "supplier"):  # чужой черновик — как несуществующий
        for url in (file_url, status_url):
            assert_error(await client.get(url, headers=staff[who].headers), 404, "NOT_FOUND")
        assert_error(await client.post(status_url, headers=staff[who].headers), 404, "NOT_FOUND")

    assert (
        await client.post(f"/api/v1/documents/{doc}/registration-request", headers=staff["manager"].headers)
    ).status_code == 200
    assert (await client.get(file_url, headers=staff["registrar"].headers)).status_code == 200  # переданный
    for who in ("accountant", "supplier"):  # без `letters.register` — по-прежнему нет
        assert_error(await client.get(file_url, headers=staff[who].headers), 404, "NOT_FOUND")


async def test_may_open_pdf_rule() -> None:
    """Правило открытия PDF проекта само по себе (не только через видимость документа): автор и делопроизводитель."""

    def employee(user: int, *permissions: str) -> Employee:
        return Employee(crm_user_id=user, permissions_eds=list(permissions))

    def letter(status: str = "draft", handed: bool = False) -> Document:
        return Document(
            author_crm_user_id=5,
            status=status,
            registration_requested_at=datetime(2026, 11, 2, tzinfo=UTC) if handed else None,
        )

    wide = ("letters.read", "registry.read")
    assert may_open_pdf(employee(5), letter())  # автор
    assert not may_open_pdf(employee(7, *wide), letter())  # чужой с широкими правами на чтение
    assert not may_open_pdf(employee(4, *wide, "letters.register"), letter())  # делопроизводитель до передачи
    assert may_open_pdf(employee(4, *wide, "letters.register"), letter(handed=True))
    assert not may_open_pdf(employee(7, *wide), letter(handed=True))  # передан, но без `letters.register`


async def test_pdf_built_before_the_mark_is_not_served(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    """PDF проекта без знака (построен до SIGN-1) не отдаётся и не показывается: экран запросит заново — со знаком."""
    manager = staff["manager"]
    doc = await draft_letter(client, container, manager)
    await make_ready(client, container, deferred, manager, doc)
    new_hash = deferred[-1]
    async with container.session_factory() as session, session.begin():
        row = await session.get(DocumentRender, new_hash)
        assert row is not None
        stale = {key: value for key, value in row.payload.items() if key != "draft"}
        old_hash = renders.digest(stale)  # так строка выглядела до SIGN-1: ввод без `draft`, свой хеш
        session.add(
            DocumentRender(
                hash=old_hash,
                status="ready",
                final=False,
                payload=stale,
                logo_sha256=row.logo_sha256,
                storage_key=row.storage_key,
                size=row.size,
                pages=1,
                last_page_fill=0.4,
                attempts=1,
                created_at=row.created_at,
                finished_at=row.finished_at,
            )
        )
        await session.flush()
        await session.execute(update(Document).where(Document.id == uuid.UUID(doc)).values(pdf_hash=old_hash))

    assert_error(await client.get(f"/api/v1/documents/{doc}/pdf/file", headers=manager.headers), 404, "NOT_FOUND")
    assert_error(await client.get(f"/api/v1/documents/{doc}/pdf", headers=manager.headers), 404, "NOT_FOUND")
    card = (await client.get(f"/api/v1/documents/{doc}", headers=manager.headers)).json()
    assert card["letter"]["pdf"] is None

    again = await client.post(f"/api/v1/documents/{doc}/pdf", headers=manager.headers)
    assert again.status_code == 202 and again.json()["status"] == "ready"  # ввод с `draft` — строка со знаком из кэша
    assert (await client.get(f"/api/v1/documents/{doc}/pdf/file", headers=manager.headers)).status_code == 200
    async with container.session_factory() as session:
        document = await session.get(Document, uuid.UUID(doc))
        assert document is not None and document.pdf_hash == new_hash != old_hash


async def test_mailing_refuses_a_draft_pdf(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    """Адресату уходит только итоговый PDF: проект в `letter_mail.start` отклоняется (последний рубеж)."""
    doc = await draft_letter(client, container, staff["manager"])
    await make_ready(client, container, deferred, staff["manager"], doc)
    async with container.session_factory() as session, session.begin():
        document = await session.get(Document, uuid.UUID(doc))
        assert document is not None and document.pdf_hash is not None
        render = await session.get(DocumentRender, document.pdf_hash)
        assert render is not None and render.final is False
        with pytest.raises(EdsError) as caught:
            await letter_mail.start(
                session, container.bus, container.storage, document=document, render=render, actor_id=5
            )
        assert caught.value.status_code == 409 and (caught.value.body.details or {})["reason"] == "pdf_not_final"
