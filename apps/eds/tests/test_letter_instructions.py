"""Поручения по входящим (P8b, SPEC-v3 §3.2a п. 2–6, pg): путь резолюции, проект делопроизводителя, резолюция трёх
типов, исполнение, перенос срока, ознакомление, права исполнителя, ИСХ «в ответ на», напоминания на фиксированном
времени, фильтры журнала."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.container import Container
from app.services import instructions
from tests.conftest import FakeClock
from tests.domain import Person, outbox, validate
from tests.helpers import seed_employee
from tests.test_api_auth import assert_error
from tests.test_files import upload
from tests.test_letter_registration import TAX_NOTICE
from tests.test_letters import NEW_LETTER

pytestmark = pytest.mark.pg

# Часы тестов: пн 2026-10-26 13:00 по Ташкенту. Исполнитель без `letters.read` — снабженец (11).
DUE = "2026-11-02"
BANK: dict[str, Any] = {
    "kind": "bank",
    "receipt_method": "post",
    "subject": "Уведомление банка об изменении тарифов",
    "sender": {"name": "АКБ «Пример Банк»"},
    "received_at": "2026-10-26",
}


async def register(client: httpx.AsyncClient, who: Person, body: dict[str, Any], **changes: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/letters", json={**body, **changes}, headers=who.headers)
    assert response.status_code == 201, response.text
    letter: dict[str, Any] = response.json()
    validate("Letter", letter)
    return letter


async def resolve(client: httpx.AsyncClient, who: Person, letter_id: str, **body: Any) -> httpx.Response:
    return await client.post(f"/api/v1/letters/{letter_id}/office-resolution", json=body, headers=who.headers)


async def act(client: httpx.AsyncClient, who: Person, instruction_id: str, op: str, body: Any) -> httpx.Response:
    return await client.post(f"/api/v1/instructions/{instruction_id}/{op}", json=body, headers=who.headers)


async def get(client: httpx.AsyncClient, who: Person, letter_id: str) -> httpx.Response:
    return await client.get(f"/api/v1/letters/{letter_id}", headers=who.headers)


async def notices(container: Container) -> list[dict[str, Any]]:
    return [e["data"] for e in await outbox(container, "notice.requested")]


async def test_tax_notice_scenario_draft_approve_extension_rejected_executed(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    """Сценарий «готово, когда»: проект делопроизводителя → директор утверждает → исполнитель просит перенос → директор
    отклоняет (срочное не продлевается) → «Исполнено» с отчётом → ВХ «Исполнено», уведомление директору."""
    registrar, director, executor = staff["registrar"], staff["director"], staff["supplier"]
    draft = {"kind": "execute", "responsible_crm_user_id": 11, "due": DUE, "text": "Подготовить пояснения по НДС."}
    letter = await register(client, registrar, TAX_NOTICE, addressee_crm_user_id=3, resolution_draft=draft)
    assert (letter["track"], letter["status"], letter["urgent"]) == ("office", "awaiting_resolution", True)
    assert letter["resolution_draft"]["responsible"] == {"crm_user_id": 11, "full_name": "Сардор Снабженцев"}
    assert letter["resolution_draft"]["drafted_by"]["crm_user_id"] == 4
    assert letter["suggested_due"] == "2026-11-04"  # срок по документу 05.11 (чт) минус рабочий день
    assert letter["resolution"] is None and letter["instructions"] == []

    # Делопроизводитель резолюцию не накладывает — только проект.
    assert_error(await resolve(client, registrar, letter["id"], **draft), 403, "FORBIDDEN")
    # Исполнитель до резолюции письма не видит.
    assert_error(await get(client, executor, letter["id"]), 403, "FORBIDDEN")

    approved = await resolve(client, director, letter["id"], **draft)  # «Утвердить» — те же поля проекта
    assert approved.status_code == 200, approved.text
    body = approved.json()
    validate("Letter", body)
    assert (body["status"], body["on_control"], body["resolution_draft"]) == ("in_execution", True, None)
    assert body["office_resolution"]["kind"] == "execute"
    assert body["office_resolution"]["responsible"]["crm_user_id"] == 11
    assert body["resolution"] is None
    [instruction] = body["instructions"]
    assert (instruction["role"], instruction["status"], instruction["due"], instruction["overdue"]) == (
        "responsible",
        "in_work",
        DUE,
        False,
    )
    assert await outbox(container, "letter.resolved") == []  # расчёт ERP не запускается
    assigned = (await notices(container))[-1]
    assert (assigned["kind"], assigned["recipients"], assigned["due"]) == ("instruction_assigned", [11], DUE)

    # Исполнитель без `letters.read` видит письмо своего поручения и задачу в «Моих задачах».
    seen = await get(client, executor, letter["id"])
    assert seen.status_code == 200, seen.text
    tasks = (await client.get("/api/v1/letter-tasks", headers=executor.headers)).json()
    validate("LetterTasks", tasks)
    assert [t["id"] for t in tasks["instructions"]] == [instruction["id"]]
    assert tasks["instructions"][0]["letter"]["number"] == letter["number"]

    # Перенос просит исполнитель; срок срочного письма не продлевается — директор может только отклонить.
    asked = await act(
        client, executor, instruction["id"], "extension", {"new_due": "2026-11-09", "reason": "Ждём банк"}
    )
    assert asked.status_code == 200, asked.text
    again = await act(client, executor, instruction["id"], "extension", {"new_due": "2026-11-10", "reason": "Ещё"})
    assert_error(again, 409, "CONFLICT", reason="extension_pending")
    director_tasks = (await client.get("/api/v1/letter-tasks", headers=director.headers)).json()
    assert [e["instruction_id"] for e in director_tasks["extensions"]] == [instruction["id"]]
    assert (await notices(container))[-1]["kind"] == "extension_requested"
    stranger = await act(client, registrar, instruction["id"], "extension/decision", {"decision": "reject"})
    assert_error(stranger, 403, "FORBIDDEN", reason="not_resolution_author")
    approve = await act(client, director, instruction["id"], "extension/decision", {"decision": "approve"})
    assert_error(approve, 409, "CONFLICT", reason="urgent_not_extendable")
    rejected = await act(
        client, director, instruction["id"], "extension/decision", {"decision": "reject", "comment": "Срок ГНК"}
    )
    assert rejected.status_code == 200, rejected.text
    [history] = rejected.json()["instructions"][0]["extensions"]
    assert (history["status"], history["old_due"], history["new_due"], history["comment"]) == (
        "rejected",
        DUE,
        "2026-11-09",
        "Срок ГНК",
    )
    assert rejected.json()["instructions"][0]["due"] == DUE
    assert (await notices(container))[-1]["kind"] == "extension_decided"

    # «Исполнено» — нужен отчёт; чужой не отмечает.
    assert_error(await act(client, executor, instruction["id"], "complete", {}), 422, "VALIDATION_FAILED")
    assert_error(
        await act(client, director, instruction["id"], "complete", {"report": "Сделано"}),
        403,
        "FORBIDDEN",
        reason="not_executor",
    )
    done = await act(client, executor, instruction["id"], "complete", {"report": "Пояснения отправлены в кабинет."})
    assert done.status_code == 200, done.text
    final = done.json()
    validate("Letter", final)
    assert (final["status"], final["on_control"]) == ("executed", False)
    assert final["executed_at"] is not None
    assert final["instructions"][0]["report"] == "Пояснения отправлены в кабинет."
    executed = (await notices(container))[-1]
    assert (executed["kind"], executed["recipients"]) == ("letter_executed", [3, 4])
    actions = [e["action"] for e in final["journal"]]
    assert actions[-2:] == ["instruction.executed", "letter.executed"]
    assert_error(
        await act(client, executor, instruction["id"], "complete", {"report": "Ещё"}),
        409,
        "CONFLICT",
        reason="invalid_state",
    )
    assert (await client.get("/api/v1/letter-tasks", headers=executor.headers)).json()["instructions"] == []


async def test_track_decides_which_resolution_applies(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    director = staff["director"]
    request = await register(client, staff["registrar"], NEW_LETTER)
    assert request["track"] == "calc" and request["suggested_due"] is None
    mismatch = await resolve(client, director, request["id"], kind="info", text="К сведению")
    assert_error(mismatch, 409, "CONFLICT", reason="track_mismatch")
    office = await register(client, staff["registrar"], BANK, links={"erp_deal_id": 905, "deal_number": "ЗВ-2026-104"})
    assert office["track"] == "office"  # вид документа задан — сделка лишь контекст
    calc = await client.post(
        f"/api/v1/letters/{office['id']}/resolution",
        json={"text": "Расчёт", "assignees": [{"crm_user_id": 11, "zone": "goods"}], "due": DUE},
        headers=director.headers,
    )
    assert_error(calc, 409, "CONFLICT", reason="track_mismatch")
    draft_on_calc = await client.put(
        f"/api/v1/letters/{request['id']}/resolution-draft", json={"kind": "info"}, headers=staff["registrar"].headers
    )
    assert_error(draft_on_calc, 409, "CONFLICT", reason="track_mismatch")


async def test_info_resolution_notes_letter_and_acquaintance(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    director, nobody = staff["director"], staff["nobody"]
    letter = await register(client, staff["registrar"], BANK)
    wrong = await resolve(client, director, letter["id"], kind="info", text="К сведению", responsible_crm_user_id=11)
    assert_error(wrong, 422, "VALIDATION_FAILED")
    noted = await resolve(client, director, letter["id"], kind="info", text="Принять к сведению.", acquaint_ids=[10, 6])
    assert noted.status_code == 200, noted.text
    body = noted.json()
    assert (body["status"], body["on_control"], body["instructions"]) == ("noted", False, [])
    assert [a["person"]["crm_user_id"] for a in body["acquaintances"]] == [10, 6]
    assert (await notices(container))[-1]["recipients"] == [10, 6]

    tasks = (await client.get("/api/v1/letter-tasks", headers=nobody.headers)).json()
    assert [a["letter"]["id"] for a in tasks["acquaintances"]] == [letter["id"]]
    assert (await get(client, nobody, letter["id"])).status_code == 200  # «ознакомить» видит письмо
    assert_error(await get(client, staff["engineer"], letter["id"]), 403, "FORBIDDEN")
    first = await client.post(f"/api/v1/letters/{letter['id']}/acquaint", headers=nobody.headers)
    assert first.status_code == 200, first.text
    mine = next(a for a in first.json()["acquaintances"] if a["person"]["crm_user_id"] == 10)
    assert mine["acknowledged_at"] is not None
    repeat = await client.post(f"/api/v1/letters/{letter['id']}/acquaint", headers=nobody.headers)
    assert repeat.status_code == 200
    assert (await client.get("/api/v1/letter-tasks", headers=nobody.headers)).json()["acquaintances"] == []
    stranger = await client.post(f"/api/v1/letters/{letter['id']}/acquaint", headers=staff["engineer"].headers)
    assert_error(stranger, 404, "NOT_FOUND")
    assert_error(await resolve(client, director, letter["id"], kind="info", text="Ещё"), 409, "CONFLICT")


async def test_validation_of_people_and_due(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    director = staff["director"]
    letter = await register(client, staff["registrar"], BANK)
    missing = await resolve(client, director, letter["id"], kind="execute", text="Сделать")
    assert_error(missing, 422, "VALIDATION_FAILED")
    past = await resolve(
        client, director, letter["id"], kind="execute", text="x", responsible_crm_user_id=11, due="2026-10-20"
    )
    assert_error(past, 422, "VALIDATION_FAILED")
    dup = await resolve(
        client,
        director,
        letter["id"],
        kind="execute",
        text="x",
        responsible_crm_user_id=11,
        due=DUE,
        co_executor_ids=[11],
    )
    assert_error(dup, 422, "VALIDATION_FAILED")
    await seed_employee(container, 77, full_name="Уволенный", is_active=False)
    inactive = await resolve(
        client, director, letter["id"], kind="reply", text="x", responsible_crm_user_id=77, due=DUE
    )
    assert_error(inactive, 422, "VALIDATION_FAILED")
    draft = await client.put(
        f"/api/v1/letters/{letter['id']}/resolution-draft",
        json={"kind": "reply", "responsible_crm_user_id": 77},
        headers=staff["registrar"].headers,
    )
    assert_error(draft, 422, "VALIDATION_FAILED")
    # Ответственный — любой активный сотрудник, без проверки зоны (у сотрудника «nobody» разделов нет).
    ok = await resolve(
        client,
        director,
        letter["id"],
        kind="execute",
        text="x",
        responsible_crm_user_id=10,
        due=DUE,
        co_executor_ids=[12],
    )
    assert ok.status_code == 200, ok.text
    assert [(i["role"], i["person"]["crm_user_id"]) for i in ok.json()["instructions"]] == [
        ("responsible", 10),
        ("co_executor", 12),
    ]


async def test_approved_extension_moves_due_and_letter_due(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    director, executor = staff["director"], staff["supplier"]
    letter = await register(client, staff["registrar"], BANK)
    body = (
        await resolve(client, director, letter["id"], kind="execute", text="x", responsible_crm_user_id=11, due=DUE)
    ).json()
    instruction_id = body["instructions"][0]["id"]
    not_later = await act(client, executor, instruction_id, "extension", {"new_due": DUE, "reason": "—"})
    assert_error(not_later, 422, "VALIDATION_FAILED")
    assert_error(
        await act(client, staff["engineer"], instruction_id, "extension", {"new_due": "2026-11-09", "reason": "—"}),
        403,
        "FORBIDDEN",
        reason="not_executor",
    )
    assert (
        await act(client, executor, instruction_id, "extension", {"new_due": "2026-11-09", "reason": "Нужны данные"})
    ).status_code == 200
    approved = await act(client, director, instruction_id, "extension/decision", {"decision": "approve"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["instructions"][0]["due"] == "2026-11-09"
    assert approved.json()["office_resolution"]["due"] == "2026-11-09"
    listed = (await client.get("/api/v1/letters", headers=director.headers)).json()["items"][0]
    assert (listed["due"], listed["executor"]["crm_user_id"]) == ("2026-11-09", 11)
    none_left = await act(client, director, instruction_id, "extension/decision", {"decision": "approve"})
    assert_error(none_left, 409, "CONFLICT", reason="no_pending_extension")


async def test_outgoing_in_reply_closes_reply_instructions(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    registrar, director = staff["registrar"], staff["director"]
    letter = await register(client, registrar, BANK)
    await resolve(
        client, director, letter["id"], kind="reply", text="Ответить банку", responsible_crm_user_id=4, due=DUE
    )
    draft = await client.post(
        "/api/v1/documents",
        json={
            "kind": "letter_out",
            "subject": "Ответ банку",
            "text": "Подтверждаем",
            "recipient": {"name": "АКБ «Пример Банк»"},
            "in_reply_to": letter["id"],
        },
        headers=registrar.headers,
    )
    assert draft.status_code == 201, draft.text
    sent = await client.post(f"/api/v1/documents/{draft.json()['id']}/submit", headers=registrar.headers)
    assert sent.status_code == 200, sent.text
    card = (await get(client, director, letter["id"])).json()
    assert card["status"] == "executed"
    assert card["instructions"][0]["outgoing"]["number"] == sent.json()["number"]
    assert (await notices(container))[-1]["kind"] == "letter_executed"


async def test_complete_with_outgoing_number_and_report_files(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    registrar, director, executor = staff["registrar"], staff["director"], staff["supplier"]
    letter = await register(client, registrar, BANK)
    body = (
        await resolve(
            client,
            director,
            letter["id"],
            kind="execute",
            text="x",
            responsible_crm_user_id=11,
            due=DUE,
            co_executor_ids=[12],
        )
    ).json()
    responsible, co = body["instructions"]
    missing = await act(client, executor, responsible["id"], "complete", {"outgoing_number": "OUT-999/26"})
    assert_error(missing, 422, "VALIDATION_FAILED")
    outgoing = await client.post(
        "/api/v1/documents",
        json={"kind": "letter_out", "subject": "Ответ", "text": "Текст", "recipient": {"name": "Банк"}},
        headers=registrar.headers,
    )
    number = (await client.post(f"/api/v1/documents/{outgoing.json()['id']}/submit", headers=registrar.headers)).json()[
        "number"
    ]
    first = await act(client, executor, responsible["id"], "complete", {"outgoing_number": number})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "in_execution"  # соисполнитель ещё работает
    ref = (await upload(client, staff["engineer"])).json()
    second = await act(client, staff["engineer"], co["id"], "complete", {"file_ids": [ref["id"]]})
    assert second.status_code == 200, second.text
    card = second.json()
    assert card["status"] == "executed"
    assert card["instructions"][1]["files"][0]["id"] == ref["id"]
    assert card["instructions"][0]["outgoing"]["number"] == number
    # Файл отчёта видят директор и исполнитель письма без `letters.read`.
    assert (await client.get(f"/api/v1/files/{ref['id']}", headers=director.headers)).status_code == 200
    assert (await client.get(f"/api/v1/files/{ref['id']}", headers=executor.headers)).status_code == 200
    assert_error(await client.get(f"/api/v1/files/{ref['id']}", headers=staff["admin"].headers), 404, "NOT_FOUND")


async def test_reminders_on_fixed_time_and_overdue(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, clock: FakeClock
) -> None:
    letter = await register(client, staff["registrar"], BANK)
    # Срок 2026-11-10 (вт): дальше 10 дней от выдачи 26.10 — напоминания за 3 дня, за рабочий день, в день срока.
    await resolve(
        client, staff["director"], letter["id"], kind="execute", text="x", responsible_crm_user_id=11, due="2026-11-10"
    )

    async def run(moment: datetime) -> list[dict[str, Any]]:
        before = len(await notices(container))
        async with container.session_factory() as session, session.begin():
            await instructions.send_reminders(session, container.bus, now=moment)
        return (await notices(container))[before:]

    assert await run(datetime(2026, 11, 5, 6, 0, tzinfo=UTC)) == []  # чт: ещё рано
    [d3] = await run(datetime(2026, 11, 6, 6, 0, tzinfo=UTC))  # 10.11 − 3 = сб → пт 06.11
    assert (d3["kind"], d3["recipients"]) == ("instruction_reminder", [11])
    assert await run(datetime(2026, 11, 6, 9, 0, tzinfo=UTC)) == []  # повтор в тот же день — ничего
    assert await run(datetime(2026, 11, 7, 6, 0, tzinfo=UTC)) == []  # сб — следующая точка в пн
    assert await run(datetime(2026, 11, 9, 2, 0, tzinfo=UTC)) == []  # пн 7:00 по Ташкенту — до 9:00 не шлём
    [d1] = await run(datetime(2026, 11, 9, 6, 0, tzinfo=UTC))
    assert "10.11.2026" in d1["title"]
    [d0] = await run(datetime(2026, 11, 10, 6, 0, tzinfo=UTC))
    assert d0["title"].startswith("Сегодня срок")
    [late] = await run(datetime(2026, 11, 11, 6, 0, tzinfo=UTC))
    assert (late["kind"], late["recipients"]) == ("instruction_overdue", [11, 3])
    assert await run(datetime(2026, 11, 12, 6, 0, tzinfo=UTC)) == []

    clock.set(datetime(2026, 11, 11, 6, 0, tzinfo=UTC))
    director = staff["director"]
    overdue = (await client.get("/api/v1/letters", params={"overdue": "true"}, headers=director.headers)).json()
    assert [r["id"] for r in overdue["items"]] == [letter["id"]]
    assert overdue["items"][0]["overdue"] is True
    tasks = (await client.get("/api/v1/letter-tasks", headers=staff["supplier"].headers)).json()
    assert tasks["instructions"][0]["overdue"] is True
    card = (await get(client, director, letter["id"])).json()
    assert card["instructions"][0]["overdue"] is True


async def test_journal_filters_and_registration_rejection_without_event(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    director = staff["director"]
    waiting = await register(client, staff["registrar"], BANK)
    controlled = await register(client, staff["registrar"], BANK, subject="Письмо госоргана")
    await resolve(client, director, controlled["id"], kind="execute", text="x", responsible_crm_user_id=11, due=DUE)

    async def ids(**params: Any) -> list[str]:
        response = await client.get("/api/v1/letters", params=params, headers=director.headers)
        assert response.status_code == 200, response.text
        validate("LetterPage", response.json())
        return [r["id"] for r in response.json()["items"]]

    assert await ids(on_control="true") == [controlled["id"]]
    assert await ids(status="awaiting_resolution") == [waiting["id"]]
    assert await ids(overdue="true") == []
    rejected = await client.post(
        f"/api/v1/letters/{waiting['id']}/reject", json={"reason": "Не нам"}, headers=director.headers
    )
    assert rejected.status_code == 200, rejected.text
    assert await outbox(container, "letter.rejected") == []  # отказ делопроизводства сделку не закрывает


async def test_draft_and_employees_rights(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    letter = await register(client, staff["registrar"], BANK)
    saved = await client.put(
        f"/api/v1/letters/{letter['id']}/resolution-draft",
        json={"kind": "info", "text": "К сведению", "acquaint_ids": [5]},
        headers=staff["registrar"].headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["resolution_draft"]["acquaint"][0]["crm_user_id"] == 5
    cleared = await client.put(
        f"/api/v1/letters/{letter['id']}/resolution-draft", json={"kind": None}, headers=staff["director"].headers
    )
    assert cleared.json()["resolution_draft"] is None
    denied = await client.put(
        f"/api/v1/letters/{letter['id']}/resolution-draft", json={"kind": "info"}, headers=staff["manager"].headers
    )
    assert_error(denied, 403, "FORBIDDEN")

    await seed_employee(container, 77, full_name="Уволенный", is_active=False)
    people = await client.get("/api/v1/employees", headers=staff["registrar"].headers)
    assert people.status_code == 200, people.text
    validate("EmployeeList", people.json())
    names = [p["full_name"] for p in people.json()["items"]]
    assert "Уволенный" not in names and names == sorted(names)
    # 1.6: список нужен любому автору документа (согласующие и копии), без прав — по-прежнему нет
    supplier = await client.get("/api/v1/employees", headers=staff["supplier"].headers)
    assert supplier.status_code == 200, supplier.text
    assert_error(await client.get("/api/v1/employees", headers=staff["nobody"].headers), 403, "FORBIDDEN")
