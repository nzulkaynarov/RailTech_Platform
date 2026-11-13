"""Одно письмо общего ящика — один ВХ (W18A-P2-3, pg): повтор регистрации возвращает прежний ВХ (200), гонка двух
регистраций даёт один ВХ благодаря уникальному индексу `uq_letters_source_mail_id`."""

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from app.services import letters as letters_service
from tests.domain import Person, outbox, validate
from tests.test_letter_registration import TAX_NOTICE

pytestmark = pytest.mark.pg


def body(mail_id: int | None = 17, **over: Any) -> dict[str, Any]:
    source = {"source": {"crm_inbound_mail_id": mail_id}} if mail_id is not None else {}
    return {**TAX_NOTICE, **source, **over}


async def post(client: httpx.AsyncClient, who: Person, payload: dict[str, Any], key: str) -> httpx.Response:
    return await client.post("/api/v1/letters", json=payload, headers={**who.headers, "Idempotency-Key": key})


async def letters_count(container: Container) -> int:
    async with container.session_factory() as session:
        return int((await session.execute(text("SELECT count(*) FROM letters"))).scalar_one())


async def test_repeat_with_another_key_returns_the_same_letter_without_a_new_number_or_event(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    who = staff["registrar"]
    first = await post(client, who, body(), "mail-17-first")
    again = await post(client, who, body(subject="Другая тема той же регистрации"), "mail-17-again")
    other = await post(client, who, body(mail_id=18, sender_ref={"number": "18"}), "mail-18-key")

    assert first.status_code == 201, first.text
    assert again.status_code == 200, again.text
    validate("Letter", again.json())
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["number"] == first.json()["number"] == "IN-001/26"
    assert again.json()["subject"] == first.json()["subject"], "повтор не меняет карточку"
    assert other.status_code == 201, other.text
    assert other.json()["number"] == "IN-002/26", "повтор номер не тратит"
    sources = [e["data"].get("source") for e in await outbox(container, "letter.registered")]
    assert sources == [{"crm_inbound_mail_id": 17}, {"crm_inbound_mail_id": 18}], "событие — один раз на письмо"


async def test_letters_without_a_mail_source_are_not_affected(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    who = staff["registrar"]
    first = await post(client, who, body(mail_id=None), "plain-key-1")
    second = await post(client, who, body(mail_id=None, sender_ref={"number": "2"}), "plain-key-2")
    assert (first.status_code, second.status_code) == (201, 201)
    assert await letters_count(container) == 2


async def test_parallel_registrations_of_one_mail_give_one_letter(
    client: httpx.AsyncClient,
    container: Container,
    staff: dict[str, Person],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Две регистрации одного письма одновременно: обе не видят ВХ до вставки (барьер в `find_by_source`), побеждает
    одна; проигравшая откатывается до точки сохранения и возвращает ВХ победившей. Без индекса — два ВХ."""
    who = staff["registrar"]
    original = letters_service.find_by_source
    gate = asyncio.Barrier(2)
    reads = 0

    async def find_then_wait(session: Any, mail_id: int) -> Any:
        nonlocal reads
        found = await original(session, mail_id)
        reads += 1
        if reads <= 2:  # оба запроса прочитали «ВХ нет» до чьей-либо вставки; повторное чтение — без ожидания
            await gate.wait()
        return found

    monkeypatch.setattr(letters_service, "find_by_source", find_then_wait)

    first, second = await asyncio.gather(
        post(client, who, body(), "race-key-a"), post(client, who, body(), "race-key-b")
    )

    assert sorted((first.status_code, second.status_code)) == [200, 201], (first.text, second.text)
    assert first.json()["id"] == second.json()["id"]
    assert await letters_count(container) == 1
    assert len(await outbox(container, "letter.registered")) == 1


async def test_mail_text_is_kept_in_the_letter_card_but_not_in_the_bus_event(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Исполнитель видит само письмо (решение владельца 2026-11-11): текст из почты — в карточке ВХ, не в событии."""
    who = staff["registrar"]
    payload = body(mail_id=21, sender_ref={"number": "21"})
    payload["source"]["text"] = "Добрый день!\nПредлагаем сотрудничество."
    created = await post(client, who, payload, "mail-21-text")
    plain = await post(client, who, body(mail_id=None, sender_ref={"number": "22"}), "plain-22")

    assert created.status_code == 201, created.text
    validate("Letter", created.json())
    assert created.json()["body_text"] == "Добрый день!\nПредлагаем сотрудничество."
    card = await client.get(f"/api/v1/letters/{created.json()['id']}", headers=who.headers)
    assert card.json()["body_text"] == "Добрый день!\nПредлагаем сотрудничество."
    assert plain.json()["body_text"] is None
    sources = [e["data"].get("source") for e in await outbox(container, "letter.registered")]
    assert {"crm_inbound_mail_id": 21} in sources
