"""Путь «ответ на входящее» (EDS-REPLY-1, pg): заготовка ответа → «Передать на регистрацию» (уведомление и задача
делопроизводителю) → регистрация ИСХ закрывает поручение и сообщает исполнителю → сбой отправки виден всем; связь
ВХ ↔ ИСХ видна с обеих сторон; «Исполнено» с номером ИСХ принимает только свой ответ или ИСХ без связи."""

from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person, outbox, validate
from tests.test_api_auth import assert_error
from tests.test_letter_instructions import BANK, DUE, act, get, notices, register, resolve
from tests.test_letterhead_letters import (
    PAIR,
    StubRenderer,
    deliver_crm,
    deliver_letterhead,
    letter_json,
    run,
)

pytestmark = pytest.mark.pg


async def reply_draft(
    client: httpx.AsyncClient, who: Person, incoming_id: str | None, **changes: Any
) -> dict[str, Any]:
    body = letter_json(**({"in_reply_to": incoming_id} if incoming_id else {}), **changes)
    created = await client.post("/api/v1/documents", json=body, headers=who.headers)
    assert created.status_code == 201, created.text
    doc: dict[str, Any] = created.json()
    validate("Document", doc)
    return doc


async def tasks_of(client: httpx.AsyncClient, who: Person) -> dict[str, Any]:
    found = await client.get("/api/v1/letter-tasks", headers=who.headers)
    assert found.status_code == 200, found.text
    body: dict[str, Any] = found.json()
    validate("LetterTasks", body)
    return body


async def incoming_for(
    client: httpx.AsyncClient, staff: dict[str, Person], *, responsible: int = 5, kind: str = "reply"
) -> dict[str, Any]:
    letter = await register(client, staff["registrar"], BANK, sender_ref={"number": "12-04/551", "date": "2026-10-24"})
    resolved = await resolve(
        client,
        staff["director"],
        letter["id"],
        kind=kind,
        text="Ответить банку",
        responsible_crm_user_id=responsible,
        due=DUE,
    )
    assert resolved.status_code == 200, resolved.text
    return letter


def notice_by_key(items: list[dict[str, Any]], suffix: str) -> dict[str, Any]:
    [found] = [n for n in items if n["notice_key"].endswith(suffix)]
    return found


async def test_reply_path_registration_task_notices_links_and_mail_failure(
    client: httpx.AsyncClient,
    staff: dict[str, Person],
    container: Container,
    deferred: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)
    registrar, director, manager = staff["registrar"], staff["director"], staff["manager"]
    await deliver_letterhead(client, container)
    incoming = await incoming_for(client, staff)

    # Черновик исполнителя: ИСХ знает ВХ (номер и тема), ВХ показывает ответ исполнителю.
    doc = await reply_draft(client, manager, incoming["id"])
    assert doc["reply_to"] == {"id": incoming["id"], "number": incoming["number"], "subject": incoming["subject"]}
    mine = (await get(client, manager, incoming["id"])).json()
    validate("Letter", mine)
    [reply] = mine["replies"]
    assert (reply["document_id"], reply["state"], reply["mail"], reply["number"]) == (doc["id"], "draft", "none", None)
    # Чужой черновик директор и делопроизводитель не видят — и блока «Ответ» у них нет.
    assert (await get(client, director, incoming["id"])).json()["replies"] == []
    assert (await get(client, registrar, incoming["id"])).json()["replies"] == []
    assert (await tasks_of(client, registrar))["registrations"] == []

    # «Передать на регистрацию»: уведомление держателям letters.register (не автору) и задача в «Моих задачах».
    handed = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=manager.headers)
    assert handed.status_code == 200, handed.text
    notice = (await notices(container))[-1]
    assert (notice["kind"], notice["recipients"]) == ("instruction_assigned", [3, 4])
    assert notice["title"] == f"Зарегистрируйте ответ на {incoming['number']}"
    assert notice["document"] == {"eds_document_id": doc["id"], "number": None, "subject": doc["subject"]}
    assert notice["letter"]["eds_letter_id"] == incoming["id"]
    again = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=manager.headers)
    assert again.status_code == 200
    assert len([n for n in await notices(container) if n.get("document")]) == 1  # повтор — без второго уведомления

    [task] = (await tasks_of(client, registrar))["registrations"]
    assert (task["document_id"], task["in_reply_to"]["number"], task["requested_by"]["crm_user_id"]) == (
        doc["id"],
        incoming["number"],
        5,
    )
    assert (await tasks_of(client, director))["registrations"] != []  # директор тоже держит letters.register
    assert (await tasks_of(client, manager))["registrations"] == []  # исполнителю без права задачи нет
    [handed_reply] = (await get(client, registrar, incoming["id"])).json()["replies"]
    assert handed_reply["state"] == "registration_requested"

    # Регистрация: задача уходит, поручение закрыто, исполнителю — уведомление, ВХ показывает ИСХ.
    registered = await client.post(
        f"/api/v1/documents/{doc['id']}/submit", json={"send": True}, headers=registrar.headers
    )
    assert registered.status_code == 200, registered.text
    number = registered.json()["number"]
    assert (await tasks_of(client, registrar))["registrations"] == []
    done = notice_by_key(await notices(container), ":registered")
    assert (done["kind"], done["recipients"]) == ("letter_executed", [5])
    assert done["title"] == f"Ответ зарегистрирован: {number}" and "поручение исполнено" in done["subtitle"]
    assert done["document"]["number"] == number
    card = (await get(client, director, incoming["id"])).json()
    assert card["status"] == "executed"
    [shown] = card["replies"]
    assert (shown["number"], shown["state"], shown["mail"]) == (number, "registered", "sending")

    # Письмо не ушло: уведомление автору и делопроизводителям, метка в карточке ВХ, повтор тем же путём.
    assert await run(container, StubRenderer(), deferred[-1]) == "ready"
    [requested] = await outbox(container, "mail.requested")
    await deliver_crm(client, container, "mail.failed", requested["data"]["request_key"], reason="smtp_not_configured")
    failed = [n for n in await notices(container) if n["notice_key"].endswith(":failed")]
    [fail] = failed
    assert (fail["kind"], fail["recipients"]) == ("instruction_assigned", [5, 3, 4])
    assert fail["title"] == f"Не отправлено: {number}"
    assert fail["subtitle"] == "Почта не настроена — Настройки · Подключения · Почта"
    assert fail["document"]["number"] == number
    [shown] = (await get(client, manager, incoming["id"])).json()["replies"]
    assert (shown["mail"], shown["mail_reason"]) == ("failed", "Почта не настроена — Настройки · Подключения · Почта")
    sent_card = (await client.get(f"/api/v1/documents/{doc['id']}", headers=registrar.headers)).json()
    assert sent_card["reply_to"]["number"] == incoming["number"]

    resend = await client.post(f"/api/v1/documents/{doc['id']}/send", headers=registrar.headers)
    assert resend.status_code == 200, resend.text
    key = (await outbox(container, "mail.requested"))[-1]["data"]["request_key"]
    await deliver_crm(client, container, "mail.sent", key)
    [shown] = (await get(client, manager, incoming["id"])).json()["replies"]
    assert (shown["mail"], shown["mail_reason"]) == ("sent", None)
    assert len([n for n in await notices(container) if n["notice_key"].endswith(":failed")]) == 1


async def test_mail_pair_secret_missing_is_reported(
    client: httpx.AsyncClient,
    staff: dict[str, Person],
    container: Container,
    deferred: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Почта не подключена к документообороту (нет секрета пары) — тоже «Не отправлено» с уведомлением."""
    monkeypatch.delenv("RT_BUS_SECRET_EDS_CRM", raising=False)
    registrar = staff["registrar"]
    await deliver_letterhead(client, container)
    incoming = await incoming_for(client, staff, responsible=4)
    doc = await reply_draft(client, registrar, incoming["id"])
    registered = await client.post(
        f"/api/v1/documents/{doc['id']}/submit", json={"send": True}, headers=registrar.headers
    )
    assert registered.status_code == 200, registered.text
    assert await run(container, StubRenderer(), deferred[-1]) == "ready"
    [fail] = [n for n in await notices(container) if n["notice_key"].endswith(":failed")]
    assert fail["recipients"] == [4, 3] and "нет секрета пары" in fail["subtitle"]
    [shown] = (await get(client, registrar, incoming["id"])).json()["replies"]
    assert shown["mail"] == "failed"
    # исполнитель и автор — один человек: регистрация сообщила только о закрытии поручения самому себе — никому
    assert [n for n in await notices(container) if n["notice_key"].endswith(":registered")] == []


async def test_reply_registered_without_mail_is_a_closed_reply(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    """Ответ вне системы (бумага, курьер): ИСХ «в ответ на» без отправки — поручение закрыто, отправки нет."""
    registrar, manager = staff["registrar"], staff["manager"]
    await deliver_letterhead(client, container)
    incoming = await incoming_for(client, staff)
    plain = letter_json(in_reply_to=incoming["id"])
    plain["letter"]["recipient_email"] = None
    doc = (await client.post("/api/v1/documents", json=plain, headers=manager.headers)).json()
    await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=manager.headers)
    registered = await client.post(f"/api/v1/documents/{doc['id']}/submit", headers=registrar.headers)
    assert registered.status_code == 200, registered.text
    [shown] = (await get(client, manager, incoming["id"])).json()["replies"]
    assert (shown["state"], shown["mail"], shown["mail_reason"]) == ("registered", "none", None)
    assert (await get(client, manager, incoming["id"])).json()["status"] == "executed"
    assert notice_by_key(await notices(container), ":registered")["recipients"] == [5]


async def test_free_letter_has_task_but_no_notice(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    """Письмо ни на что не отвечает: задача делопроизводителю есть, уведомления нет (в событии `letter` обязателен)."""
    manager, registrar = staff["manager"], staff["registrar"]
    doc = await reply_draft(client, manager, None)
    assert doc["reply_to"] is None
    before = len(await notices(container))
    assert (
        await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=manager.headers)
    ).status_code == 200
    assert len(await notices(container)) == before
    [task] = (await tasks_of(client, registrar))["registrations"]
    assert task["in_reply_to"] is None


async def test_complete_with_outgoing_links_or_refuses_foreign_reply(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    registrar, manager = staff["registrar"], staff["manager"]
    await deliver_letterhead(client, container)
    incoming = await incoming_for(client, staff, kind="execute")
    other = await register(client, registrar, {**BANK, "subject": "Другое письмо банка"})
    instruction = (await get(client, manager, incoming["id"])).json()["instructions"][0]

    async def send(in_reply_to: str | None) -> str:
        doc = await reply_draft(client, registrar, in_reply_to)
        sent = await client.post(f"/api/v1/documents/{doc['id']}/submit", headers=registrar.headers)
        assert sent.status_code == 200, sent.text
        return str(sent.json()["number"])

    foreign = await send(other["id"])
    refused = await act(client, manager, instruction["id"], "complete", {"outgoing_number": foreign})
    assert_error(refused, 409, "CONFLICT", reason="outgoing_linked_elsewhere")
    assert other["number"] in refused.json()["message"]
    assert (await get(client, manager, incoming["id"])).json()["instructions"][0]["status"] == "in_work"

    free = await send(None)
    accepted = await act(client, manager, instruction["id"], "complete", {"outgoing_number": free})
    assert accepted.status_code == 200, accepted.text
    card = accepted.json()
    assert card["instructions"][0]["outgoing"]["number"] == free and card["status"] == "executed"
    [linked] = card["replies"]  # связь записана: ИСХ теперь «в ответ на» это ВХ
    assert (linked["number"], linked["state"]) == (free, "registered")
    docs = (await client.get("/api/v1/documents?kind=letter_out", headers=registrar.headers)).json()["items"]
    free_id = next(d["id"] for d in docs if d["number"] == free)
    card_doc = (await client.get(f"/api/v1/documents/{free_id}", headers=registrar.headers)).json()
    assert card_doc["reply_to"]["number"] == incoming["number"]
    assert "document.reply_linked" in [e["action"] for e in card_doc["journal"]]
