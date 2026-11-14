"""Исходы письма (решение владельца 2026-11-11): «Закрыть без ответа» с причиной из справочника, «Вернуть в работу»
автором резолюции, «Вернуть автору» ответственным."""

from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person, validate
from tests.test_api_auth import assert_error
from tests.test_letter_instructions import BANK, DUE, act, get, notices, register, resolve

pytestmark = pytest.mark.pg


async def in_execution(client: httpx.AsyncClient, staff: dict[str, Person]) -> dict[str, Any]:
    """Письмо банка: ответственный — снабженец (11), соисполнитель — инженер (12)."""
    letter = await register(client, staff["registrar"], BANK)
    resolved = await resolve(
        client,
        staff["director"],
        letter["id"],
        kind="execute",
        text="Разобраться с тарифами",
        responsible_crm_user_id=11,
        due=DUE,
        co_executor_ids=[12],
    )
    assert resolved.status_code == 200, resolved.text
    body: dict[str, Any] = resolved.json()
    return body


def by_person(card: dict[str, Any], crm_user_id: int) -> dict[str, Any]:
    return next(i for i in card["instructions"] if i["person"]["crm_user_id"] == crm_user_id)


async def close(client: httpx.AsyncClient, who: Person, letter_id: str, **body: Any) -> httpx.Response:
    return await client.post(f"/api/v1/letters/{letter_id}/close", json=body, headers=who.headers)


async def test_close_without_reply_then_author_reopens(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    letter = await in_execution(client, staff)
    supplier, engineer, director = staff["supplier"], staff["engineer"], staff["director"]

    # Только ответственный; причина из справочника; у «Недобросовестный контрагент» пояснение обязательно.
    assert_error(await close(client, engineer, letter["id"], reason="no_reply_needed"), 403, "FORBIDDEN")
    assert_error(await close(client, supplier, letter["id"], reason="nope"), 422, "VALIDATION_FAILED")
    assert_error(
        await close(client, supplier, letter["id"], reason="unreliable_counterparty"), 422, "VALIDATION_FAILED"
    )

    closed = await close(
        client, supplier, letter["id"], reason="unreliable_counterparty", comment="Срывал поставки в 2025 году"
    )
    assert closed.status_code == 200, closed.text
    card = closed.json()
    validate("Letter", card)
    assert (card["status"], card["on_control"], card["close_reason"]) == ("closed", False, "unreliable_counterparty")
    assert by_person(card, 11)["status"] == "executed"
    assert (
        by_person(card, 11)["report"] == "Закрыто без ответа: Недобросовестный контрагент. Срывал поставки в 2025 году"
    )
    assert by_person(card, 12)["status"] == "cancelled"
    notice = (await notices(container))[-1]
    assert (notice["kind"], notice["recipients"]) == ("letter_executed", [3])
    assert notice["title"] == f"Закрыто без ответа: {letter['number']}"

    # Вернуть в работу — только автор резолюции; поручения снова в работе.
    assert_error(
        await client.post(f"/api/v1/letters/{letter['id']}/reopen", headers=supplier.headers), 403, "FORBIDDEN"
    )
    reopened = await client.post(f"/api/v1/letters/{letter['id']}/reopen", headers=director.headers)
    assert reopened.status_code == 200, reopened.text
    card = reopened.json()
    assert (card["status"], card["on_control"], card["close_reason"]) == ("in_execution", True, None)
    assert {i["status"] for i in card["instructions"]} == {"in_work"}
    assert sorted((await notices(container))[-1]["recipients"]) == [11, 12]


async def test_return_to_author_clears_the_resolution_and_allows_a_new_one(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    letter = await in_execution(client, staff)
    supplier, engineer, director = staff["supplier"], staff["engineer"], staff["director"]
    mine = by_person(letter, 11)

    assert_error(
        await act(client, engineer, by_person(letter, 12)["id"], "return", {"reason": "не моё"}), 403, "FORBIDDEN"
    )
    returned = await act(client, supplier, mine["id"], "return", {"reason": "Это вопрос бухгалтерии"})
    assert returned.status_code == 200, returned.text
    card = returned.json()
    validate("Letter", card)
    assert (card["status"], card["on_control"], card["instructions"]) == ("awaiting_resolution", False, [])
    notice = (await notices(container))[-1]
    assert (notice["recipients"], notice["title"]) == ([3], f"Вернули письмо: {letter['number']}")

    # Новая резолюция на того же сотрудника проходит (старые поручения сняты).
    again = await resolve(
        client, director, letter["id"], kind="execute", text="Бухгалтерии", responsible_crm_user_id=11, due=DUE
    )
    assert again.status_code == 200, again.text
    assert [i["person"]["crm_user_id"] for i in again.json()["instructions"]] == [11]


async def test_cannot_return_after_someone_executed(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    letter = await in_execution(client, staff)
    done = await act(client, staff["engineer"], by_person(letter, 12)["id"], "complete", {"report": "Сверил тарифы"})
    assert done.status_code == 200, done.text
    refused = await act(client, staff["supplier"], by_person(letter, 11)["id"], "return", {"reason": "не моё"})
    assert_error(refused, 409, "CONFLICT", reason="instruction_executed")
    assert (await get(client, staff["supplier"], letter["id"])).json()["status"] == "in_execution"


async def test_close_reasons_are_a_dictionary(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    listed = await client.get("/api/v1/dictionaries/close-reasons", headers=staff["admin"].headers)
    assert listed.status_code == 200, listed.text
    items = {i["code"]: i for i in listed.json()["items"]}
    assert list(items) == ["no_reply_needed", "advertising", "unreliable_counterparty", "other"]
    assert items["other"]["attrs"]["comment_required"] is True


# ── План 1.9: соисполнителей привлекает ответственный ───────────────────────────────────────────


async def add_co(client: httpx.AsyncClient, who: Person, letter_id: str, **body: Any) -> httpx.Response:
    return await client.post(f"/api/v1/letters/{letter_id}/co-executors", json=body, headers=who.headers)


async def test_responsible_adds_a_co_executor_who_reports_back(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    import datetime as dt

    letter = await in_execution(client, staff)
    supplier, engineer, accountant = staff["supplier"], staff["engineer"], staff["accountant"]
    task = {"crm_user_id": accountant.id, "text": "Сверить тарифы с договором банка", "due": DUE}

    assert_error(await add_co(client, engineer, letter["id"], **task), 403, "FORBIDDEN")
    later = (dt.date.fromisoformat(DUE) + dt.timedelta(days=5)).isoformat()
    assert_error(await add_co(client, supplier, letter["id"], **{**task, "due": later}), 422, "VALIDATION_FAILED")
    assert_error(
        await add_co(client, supplier, letter["id"], **{**task, "crm_user_id": engineer.id}), 422, "VALIDATION_FAILED"
    )

    added = await add_co(client, supplier, letter["id"], **task)
    assert added.status_code == 200, added.text
    card = added.json()
    validate("Letter", card)
    mine = by_person(card, accountant.id)
    assert (mine["role"], mine["status"], mine["text"]) == (
        "co_executor",
        "in_work",
        "Сверить тарифы с договором банка",
    )
    notice = (await notices(container))[-1]
    assert (notice["kind"], notice["recipients"]) == ("instruction_assigned", [accountant.id])

    done = await client.post(
        f"/api/v1/instructions/{mine['id']}/complete", json={"report": "Тарифы совпадают"}, headers=accountant.headers
    )
    assert done.status_code == 200, done.text
    notice = (await notices(container))[-1]
    assert (notice["kind"], notice["recipients"]) == ("letter_executed", [supplier.id])
    assert notice["title"] == f"Соисполнитель отчитался: {letter['number']}"
    assert done.json()["status"] == "in_execution", "исход письма выбирает ответственный"


async def complete(client: httpx.AsyncClient, who: Person, instruction_id: str, **body: Any) -> httpx.Response:
    return await client.post(f"/api/v1/instructions/{instruction_id}/complete", json=body, headers=who.headers)


async def test_hand_over_to_a_memo_closes_the_instruction_with_a_link(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    from tests.test_documents import create

    letter = await in_execution(client, staff)
    supplier, engineer = staff["supplier"], staff["engineer"]
    mine = by_person(letter, supplier.id)
    memo = await create(client, supplier, subject="Участие в конференции банка")
    alien = await create(client, engineer, subject="Чужая записка")
    hand = {"kind": "memo", "ref": memo["id"], "number": "подменённый"}

    # Исход письма выбирает ответственный: соисполнитель не передаёт в работу
    co = by_person(letter, engineer.id)
    refused = await complete(client, engineer, co["id"], handed_to={**hand, "ref": alien["id"]})
    assert_error(refused, 403, "FORBIDDEN")
    assert refused.json()["details"]["reason"] == "not_responsible"
    # Чужая записка и выдуманный id — не найдены
    for ref in (alien["id"], "00000000-0000-7000-8000-000000000000", "не-uuid"):
        missing = await complete(client, supplier, mine["id"], handed_to={**hand, "ref": ref})
        assert_error(missing, 422, "VALIDATION_FAILED")

    done = await complete(client, supplier, mine["id"], handed_to=hand)
    assert done.status_code == 200, done.text
    card = done.json()
    validate("Letter", card)
    executed = by_person(card, supplier.id)
    assert executed["status"] == "executed"
    assert executed["handed_to"] == {"kind": "memo", "ref": memo["id"], "number": memo["number"]}
    journal = [e["comment"] for e in card["journal"] if e["action"] == "instruction.executed"]
    assert journal == [f"Передано в работу: служебная записка {memo['number']}"]
    assert by_person(card, engineer.id)["handed_to"] is None


async def test_hand_over_to_a_client_request_keeps_the_number_from_bff(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    letter = await in_execution(client, staff)
    supplier = staff["supplier"]
    mine = by_person(letter, supplier.id)
    hand = {"kind": "client_request", "ref": "4512", "number": "З-0045"}
    done = await complete(client, supplier, mine["id"], handed_to=hand, report="Клиент просит КП")
    assert done.status_code == 200, done.text
    executed = by_person(done.json(), supplier.id)
    assert executed["handed_to"] == hand
    assert executed["report"] == "Клиент просит КП"
    bad = await complete(client, supplier, mine["id"], handed_to={**hand, "kind": "deal"})
    assert_error(bad, 422, "VALIDATION_FAILED")
