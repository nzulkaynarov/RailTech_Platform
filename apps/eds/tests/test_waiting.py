"""«Вы ждёте других» (ГЛ-1, pg): строки выводятся из фактов (письмо на подписи, открытый маршрут, поручение в работе);
«Напомнить» повторяет существующее уведомление адресату и не чаще раза в час."""

from typing import Any

import httpx
import pytest

from app.container import Container
from tests.conftest import FakeClock
from tests.domain import Person, outbox, validate
from tests.test_api_auth import assert_error
from tests.test_document_notices import authorise, hand_over, notices
from tests.test_documents import WITH_AMOUNT, create, decide, submit
from tests.test_letter_instructions import DUE
from tests.test_letter_instructions import notices as instruction_notices
from tests.test_letterhead_letters import deliver_letterhead
from tests.test_reply_path import incoming_for

pytestmark = pytest.mark.pg


async def waiting(client: httpx.AsyncClient, who: Person) -> dict[str, Any]:
    response = await client.get("/api/v1/waiting", headers=who.headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    validate("WaitingList", body)
    return body


async def remind(client: httpx.AsyncClient, who: Person, kind: str, object_id: str) -> httpx.Response:
    return await client.post(f"/api/v1/waiting/{kind}/{object_id}/remind", headers=who.headers)


async def test_letter_on_signature_is_waiting_on_the_signer_until_signed(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await deliver_letterhead(client, container)
    await authorise(client, staff)  # подписант — директор (id 3)
    manager = staff["manager"]
    assert (await waiting(client, manager))["items"] == []  # передачи не было — ничего не ждём

    doc = await hand_over(client, manager)
    [row] = (await waiting(client, manager))["items"]
    assert (row["kind"], row["object_id"], row["remindable"]) == ("letter_signature", doc["id"], True)
    assert row["waiting_on"] == {"crm_user_id": 3, "full_name": staff["director"].name}
    assert (await waiting(client, staff["director"]))["items"] == []  # у подписанта это не «жду других»

    assert (
        await client.post(f"/api/v1/documents/{doc['id']}/sign", json={}, headers=staff["director"].headers)
    ).status_code == 200
    assert (await waiting(client, manager))["items"] == []  # подписано — строка гаснет сама


async def test_remind_resends_the_signing_notice_once_an_hour(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, clock: FakeClock
) -> None:
    await deliver_letterhead(client, container)
    await authorise(client, staff)
    manager = staff["manager"]
    doc = await hand_over(client, manager)
    before = len(await notices(container, "letter_sign_requested"))

    first = await remind(client, manager, "letter_signature", doc["id"])
    assert first.status_code == 200, first.text
    validate("RemindOut", first.json())
    sent = await notices(container, "letter_sign_requested")
    assert len(sent) == before + 1 and sent[-1]["recipients"] == [3]

    again = await remind(client, manager, "letter_signature", doc["id"])
    assert_error(again, 429, "RATE_LIMITED")
    assert again.headers["retry-after"].isdigit()
    assert len(await notices(container, "letter_sign_requested")) == before + 1  # второй раз ничего не ушло
    [row] = (await waiting(client, manager))["items"]
    assert (row["remindable"], row["remind_available_at"] is not None) == (False, True)

    clock.advance(hours=1, minutes=1)
    assert (await remind(client, manager, "letter_signature", doc["id"])).status_code == 200
    assert len(await notices(container, "letter_sign_requested")) == before + 2


async def test_letter_reminder_is_one_fact_for_the_card_and_the_waiting_list(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, clock: FakeClock
) -> None:
    """ГЛ-0 «Напомнить» на карточке и ГЛ-1 «Напомнить» в «Вы ждёте других» делят один час: напоминание любым путём
    закрывает оба, и строка очереди сама показывает, что напоминать пока нельзя."""
    await deliver_letterhead(client, container)
    await authorise(client, staff)
    manager = staff["manager"]
    card_url = "/api/v1/documents/{}/remind"

    first = await hand_over(client, manager)
    assert (await client.post(card_url.format(first["id"]), headers=manager.headers)).status_code == 200
    assert_error(await remind(client, manager, "letter_signature", first["id"]), 429, "RATE_LIMITED")
    [row] = (await waiting(client, manager))["items"]
    assert (row["remindable"], row["remind_available_at"] is not None) == (False, True)

    clock.advance(hours=1, minutes=1)
    second = await hand_over(client, manager)
    assert (await remind(client, manager, "letter_signature", second["id"])).status_code == 200
    blocked = await client.post(card_url.format(second["id"]), headers=manager.headers)
    assert_error(blocked, 409, "CONFLICT")
    assert blocked.json()["details"]["reason"] == "remind_too_soon"


async def test_remind_is_only_for_the_author_and_not_when_signer_is_the_author(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await deliver_letterhead(client, container)
    manager = staff["manager"]
    doc = await hand_over(client, manager)  # реестра полномочий нет — подписанта нет
    [row] = (await waiting(client, manager))["items"]
    assert (row["waiting_on"], row["remindable"]) == (None, False)
    assert_error(await remind(client, manager, "letter_signature", doc["id"]), 409, "CONFLICT")
    assert_error(await remind(client, staff["registrar"], "letter_signature", doc["id"]), 404, "NOT_FOUND")


async def test_memo_on_approval_waits_on_the_current_step_and_clears_after_decision(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    manager = staff["manager"]
    doc = await create(client, manager, **WITH_AMOUNT)
    approval_id = (await submit(client, manager, doc["id"])).json()["approval_id"]
    [row] = [i for i in (await waiting(client, manager))["items"] if i["kind"] == "approval"]
    assert row["object_id"] == approval_id and row["title"] == doc["subject"]
    assert row["waiting_on"] is not None or row["waiting_label"]

    opened = len(await outbox(container, "approval.requested"))
    before = len(await notices(container, "approval_reminder"))
    assert (await remind(client, manager, "approval", approval_id)).status_code == 200
    sent = (await notices(container, "approval_reminder"))[before:]
    # a person gets it: the holders of the step's right, never the author; the circle is not "opened" again
    assert len(sent) == 1 and sent[0]["recipients"] and manager.id not in sent[0]["recipients"]
    assert staff["director"].id in sent[0]["recipients"]
    assert len(await outbox(container, "approval.requested")) == opened
    assert_error(await remind(client, manager, "approval", approval_id), 429, "RATE_LIMITED")

    assert (await decide(client, staff["director"], approval_id, "reject", comment="Нет бюджета")).status_code == 200
    assert [i for i in (await waiting(client, manager))["items"] if i["kind"] == "approval"] == []
    assert_error(await remind(client, manager, "approval", approval_id), 404, "NOT_FOUND")


async def test_issued_instruction_waits_on_the_executor_until_executed(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    letter = await incoming_for(client, staff, responsible=11, kind="execute")
    director, executor = staff["director"], staff["supplier"]
    [row] = (await waiting(client, director))["items"]
    assert (row["kind"], row["number"], row["due"]) == ("instruction", letter["number"], DUE)
    assert row["waiting_on"]["crm_user_id"] == executor.id
    assert (await waiting(client, executor))["items"] == []

    before = len(await instruction_notices(container))
    assert (await remind(client, director, "instruction", row["object_id"])).status_code == 200
    sent = (await instruction_notices(container))[before:]
    assert [(n["kind"], n["recipients"]) for n in sent] == [("instruction_reminder", [executor.id])]
    assert_error(await remind(client, director, "instruction", row["object_id"]), 429, "RATE_LIMITED")
    assert_error(await remind(client, executor, "instruction", row["object_id"]), 404, "NOT_FOUND")

    done = await client.post(
        f"/api/v1/instructions/{row['object_id']}/complete", json={"report": "Сделано"}, headers=executor.headers
    )
    assert done.status_code == 200, done.text
    assert (await waiting(client, director))["items"] == []


async def test_remind_has_no_one_to_remind_when_the_author_is_the_only_approver(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    director = staff["director"]
    doc = await create(client, director, **WITH_AMOUNT)
    approval_id = (await submit(client, director, doc["id"])).json()["approval_id"]
    [row] = [i for i in (await waiting(client, director))["items"] if i["kind"] == "approval"]
    assert row["remindable"] is False  # the only holder of the step's right is the author

    before = len(await notices(container, "approval_reminder"))
    assert_error(await remind(client, director, "approval", approval_id), 409, "CONFLICT")
    assert len(await notices(container, "approval_reminder")) == before
