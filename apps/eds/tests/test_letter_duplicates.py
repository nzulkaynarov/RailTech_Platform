"""Одно письмо — один входящий номер (EDS-DUP, pg): точный дубль — 409, `force` с причиной в журнал, похожие —
предупреждение, нормализация корреспондента, гонка двух регистраций, «Это дубль IN-…» и права."""

import asyncio
from datetime import date
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from app.services.letter_dedup import exact_key, letter_number, name_key, ref_key
from tests.domain import Person, validate
from tests.test_api_auth import assert_error
from tests.test_files import PDF, upload
from tests.test_letter_instructions import DUE, resolve
from tests.test_letter_registration import TAX_NOTICE

pytestmark = pytest.mark.pg

SUPPLIER: dict[str, Any] = {
    "kind": "supplier",
    "receipt_method": "post",
    "subject": "Акт сверки за октябрь",
    "sender": {"name": "ООО «Пример Сталь»", "inn": "301234567"},
    "sender_ref": {"number": "№ 12/45", "date": "2026-10-20"},
    "received_at": "2026-10-24",
}


async def register(client: httpx.AsyncClient, who: Person, body: dict[str, Any], **changes: Any) -> httpx.Response:
    return await client.post("/api/v1/letters", json={**body, **changes}, headers=who.headers)


async def check(client: httpx.AsyncClient, who: Person, **body: Any) -> list[tuple[str, str]]:
    response = await client.post("/api/v1/letters/duplicates-check", json=body, headers=who.headers)
    assert response.status_code == 200, response.text
    validate("LetterDuplicateCheck", response.json())
    return [(item["number"], item["match"]) for item in response.json()["items"]]


async def mark(client: httpx.AsyncClient, who: Person, letter_id: str, **body: Any) -> httpx.Response:
    return await client.post(f"/api/v1/letters/{letter_id}/duplicate", json=body, headers=who.headers)


def test_correspondent_and_number_normalization() -> None:
    same = {
        "ООО «Пример Сталь»",
        'OOO "Пример Сталь"',
        "Пример  сталь LLC",
        "«ПРИМЕР СТАЛЬ» MChJ",
        "пример сталь, ооо",
        "Пример Сталь МЧЖ",
    }
    assert {name_key(n) for n in same} == {"пример сталь"}
    assert name_key("ООО «Пример Сталь-2»") != "пример сталь"
    assert ref_key(" № 12/45 ") == ref_key("12/45") == "12/45"
    assert ref_key("04-12/А") == ref_key("04-12/а")
    day = date(2026, 10, 20)
    assert exact_key("301234567", "x", None, "12/45", day) == "12/45|2026-10-20|i:301234567"
    assert exact_key(None, "ООО «Пример»", None, "12/45", day) == "12/45|2026-10-20|n:пример"
    assert exact_key(None, None, 42, "12/45", day) == "12/45|2026-10-20|c:42"
    assert exact_key(None, "Пример", None, "12/45", None) is None
    assert exact_key(None, "Пример", None, " ", day) is None
    assert exact_key(None, None, None, "12/45", day) is None


async def test_exact_duplicate_is_409_with_the_existing_letter(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    registrar = staff["registrar"]
    first = await register(client, registrar, SUPPLIER)
    assert first.status_code == 201, first.text
    # Тот же корреспондент другим написанием, тот же номер с пробелом и «№», та же дата, другая тема — то же письмо.
    again = await register(
        client,
        registrar,
        SUPPLIER,
        subject="Другая тема",
        sender={"name": 'OOO "Пример сталь"', "inn": "301234567"},
        sender_ref={"number": "12/45 ", "date": "2026-10-20"},
    )
    assert_error(again, 409, "CONFLICT", reason="duplicate_letter")
    duplicate = again.json()["details"]["duplicate"]
    validate("LetterDuplicate", duplicate)
    assert (duplicate["number"], duplicate["status"], duplicate["match"]) == (
        "IN-001/26",
        "awaiting_resolution",
        "exact",
    )
    assert "IN-001/26" in again.json()["message"]
    # Без ИНН — по названию; ИНН у обоих разный — другой корреспондент.
    by_name = await register(client, registrar, SUPPLIER, sender={"name": "Пример Сталь LLC"})
    assert_error(by_name, 409, "CONFLICT", reason="duplicate_letter")
    other_inn = await register(client, registrar, SUPPLIER, sender={"name": "ООО «Пример Сталь»", "inn": "309999999"})
    assert other_inn.status_code == 201, other_inn.text
    # Другая дата исходящего — не то же письмо.
    other_date = await register(client, registrar, SUPPLIER, sender_ref={"number": "12/45", "date": "2026-10-21"})
    assert other_date.status_code == 201, other_date.text


async def test_force_needs_a_reason_and_writes_it_to_the_journal(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    registrar = staff["registrar"]
    assert (await register(client, registrar, SUPPLIER)).status_code == 201
    no_reason = await register(client, registrar, SUPPLIER, force=True)
    assert_error(no_reason, 422, "VALIDATION_FAILED")
    assert no_reason.json()["details"]["fields"][0] == {
        "field": "force_reason",
        "message": "required",
        "type": "value_error",
    }
    blank = await register(client, registrar, SUPPLIER, force=True, force_reason="  ")
    assert_error(blank, 422, "VALIDATION_FAILED")
    forced = await register(client, registrar, SUPPLIER, force=True, force_reason="Повторное письмо с исправлением")
    assert forced.status_code == 201, forced.text
    letter = forced.json()
    assert letter["number"] == "IN-002/26"  # номер без пропуска: отказы выше номера не тратят
    entry = next(e for e in letter["journal"] if e["action"] == "letter.duplicate_forced")
    assert entry["comment"] == "Совпадает с IN-001/26: Повторное письмо с исправлением"
    assert entry["by"]["crm_user_id"] == registrar.id
    # Третья копия снова упирается в оригинал.
    assert_error(await register(client, registrar, SUPPLIER), 409, "CONFLICT", reason="duplicate_letter")


async def test_similar_letters_warn_but_do_not_block(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    registrar = staff["registrar"]
    file_ref = (await upload(client, registrar)).json()
    first = await register(client, registrar, SUPPLIER, file_ids=[file_ref["id"]])
    assert first.status_code == 201, first.text
    sender = {"name": "Пример Сталь MChJ"}

    # Точное — первым; похожее по теме за ±3 дня, по номеру с другой датой, по тому же файлу.
    assert await check(client, registrar, sender=sender, sender_ref=SUPPLIER["sender_ref"]) == [("IN-001/26", "exact")]
    subject = {"sender": sender, "subject": " акт  сверки за октябрь.", "received_at": "2026-10-27"}
    assert await check(client, registrar, **subject) == [("IN-001/26", "same_subject")]
    assert await check(client, registrar, **{**subject, "received_at": "2026-10-28"}) == []  # 4 дня — не похоже
    assert await check(client, registrar, **{**subject, "sender": {"name": "Другой поставщик"}}) == []
    ref = {"number": "12/45", "date": "2026-10-01"}
    assert await check(client, registrar, sender=sender, sender_ref=ref) == [("IN-001/26", "same_ref")]
    again = (await upload(client, registrar)).json()  # тот же файл ещё раз — тот же SHA-256
    assert await check(client, registrar, file_ids=[again["id"]]) == [("IN-001/26", "same_file")]
    other = (await upload(client, registrar, PDF + b"other")).json()
    assert await check(client, registrar, file_ids=[other["id"]]) == []
    # Похожее регистрировать не мешает.
    similar = await register(client, registrar, SUPPLIER, sender_ref=None, received_at="2026-10-27")
    assert similar.status_code == 201, similar.text
    assert await check(client, registrar) == []


async def test_two_parallel_registrations_of_one_letter_give_one_number(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    """Гонка: обе регистрации прошли предварительную проверку; уникальный индекс пропускает одну, вторая — 409."""
    responses = await asyncio.gather(*(register(client, staff["registrar"], SUPPLIER) for _ in range(5)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409, 409], [r.text for r in responses]
    for loser in (r for r in responses if r.status_code == 409):
        assert loser.json()["details"]["reason"] == "duplicate_letter"
        assert loser.json()["details"]["duplicate"]["number"] == "IN-001/26"
    listed = (await client.get("/api/v1/letters", headers=staff["registrar"].headers)).json()
    assert [item["number"] for item in listed["items"]] == ["IN-001/26"]


async def test_mark_duplicate_closes_letter_and_cancels_its_work(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    registrar, director, executor = staff["registrar"], staff["director"], staff["supplier"]
    original = (await register(client, registrar, TAX_NOTICE)).json()
    copy = (await register(client, registrar, TAX_NOTICE, force=True, force_reason="Пришло дважды")).json()
    resolved = await resolve(
        client,
        director,
        copy["id"],
        kind="execute",
        responsible_crm_user_id=11,
        co_executor_ids=[12],
        acquaint_ids=[10],
        due=DUE,
        text="Подготовить пояснения.",
    )
    assert resolved.status_code == 200, resolved.text
    [first, _] = resolved.json()["instructions"]
    asked = await client.post(
        f"/api/v1/instructions/{first['id']}/extension",
        json={"new_due": "2026-11-03", "reason": "Ждём банк"},
        headers=executor.headers,
    )
    assert asked.status_code == 200, asked.text

    # Резолюция уже наложена — без подтверждения нельзя.
    unconfirmed = await mark(client, registrar, copy["id"], original_number=original["number"])
    assert_error(unconfirmed, 409, "CONFLICT", reason="resolution_exists")
    assert unconfirmed.json()["details"]["instructions"] == 2
    done = await mark(client, registrar, copy["id"], original_number=original["number"], confirm=True, comment="Копия")
    assert done.status_code == 200, done.text
    body = done.json()
    validate("Letter", body)
    assert (body["status"], body["on_control"], body["number"]) == ("duplicate", False, copy["number"])
    assert body["duplicate_of"] == {"id": original["id"], "number": original["number"]}
    assert {i["status"] for i in body["instructions"]} == {"cancelled"}
    assert body["instructions"][0]["extensions"][0]["status"] == "rejected"
    assert body["acquaintances"] == []
    actions = {e["action"]: e["comment"] for e in body["journal"]}
    assert actions["letter.marked_duplicate"] == f"Дубль {original['number']}: Копия"
    assert actions["letter.work_cancelled"].startswith("Отменено поручений: 2, ознакомлений: 1.")

    # Ни задач, ни контроля, ни «Ждёт резолюции».
    for who in (executor, staff["engineer"], staff["nobody"]):
        tasks = (await client.get("/api/v1/letter-tasks", headers=who.headers)).json()
        assert tasks == {"instructions": [], "extensions": [], "acquaintances": [], "registrations": []}
    director_tasks = (await client.get("/api/v1/letter-tasks", headers=director.headers)).json()
    assert director_tasks["extensions"] == []
    for params in ({"on_control": "true"}, {"status": "awaiting_resolution"}):
        page = (await client.get("/api/v1/letters", params=params, headers=registrar.headers)).json()
        assert copy["id"] not in [item["id"] for item in page["items"]]
    complete = await client.post(f"/api/v1/instructions/{first['id']}/complete", json={}, headers=executor.headers)
    assert_error(complete, 409, "CONFLICT", reason="invalid_state")

    linked = (await client.get(f"/api/v1/letters/{original['id']}", headers=registrar.headers)).json()
    assert any(e["action"] == "letter.duplicate_linked" and copy["number"] in e["comment"] for e in linked["journal"])
    # Ещё раз — уже дубль; номер ВХ не освобождается.
    assert_error(await mark(client, registrar, copy["id"], original_number=original["number"]), 409, "CONFLICT")
    nxt = await register(client, registrar, TAX_NOTICE, sender_ref={"number": "04-12/7777", "date": "2026-10-28"})
    assert nxt.json()["number"] == "IN-003/26"


async def test_mark_duplicate_validation_and_rights(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    registrar = staff["registrar"]
    original = (await register(client, registrar, SUPPLIER)).json()
    copy = (await register(client, registrar, SUPPLIER, force=True, force_reason="Тест")).json()
    for number, reason in (("IN-999/26", "not_found"), (copy["number"], "same_letter")):
        wrong = await mark(client, registrar, copy["id"], original_number=number)
        assert_error(wrong, 422, "VALIDATION_FAILED")
        assert wrong.json()["details"]["fields"][0]["message"] == reason
    for who in ("director", "manager", "nobody"):  # «Это дубль» — у делопроизводителя (`letters.register`)
        if "letters.register" in staff[who].permissions:
            continue
        denied = await mark(client, staff[who], copy["id"], original_number=original["number"])
        assert_error(denied, 403, "FORBIDDEN", permission="letters.register")
    # Без резолюции — без подтверждения; оригинал-дубль не принимается.
    assert (await mark(client, registrar, copy["id"], original_number=original["number"])).status_code == 200
    third = (await register(client, registrar, SUPPLIER, force=True, force_reason="Тест 2")).json()
    to_dup = await mark(client, registrar, third["id"], original_number=copy["number"])
    assert to_dup.json()["details"]["fields"][0]["message"] == "original_is_duplicate"
    assert_error(
        await mark(client, registrar, "00000000-0000-0000-0000-000000000000", original_number="IN-001/26"),
        404,
        "NOT_FOUND",
    )


async def test_duplicates_check_needs_reading_or_registering(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    for who in ("supplier", "nobody"):
        denied = await client.post("/api/v1/letters/duplicates-check", json={}, headers=staff[who].headers)
        assert_error(denied, 403, "FORBIDDEN")
    assert await check(client, staff["manager"]) == []


def test_no_number_is_an_empty_number_and_original_number_is_forgiving() -> None:
    for empty in ("б/н", "Б/Н", "бн", "b/n", "-", "—", "нет", "без номера", "№", " / ", "..."):
        assert ref_key(empty) == "", empty
        assert exact_key("301234567", None, None, empty, date(2026, 10, 20)) is None, empty
    assert ref_key("Н-1") == "н-1"
    assert letter_number(" in-001/26 ") == "IN-001/26"  # нынешнее обозначение — как набрано, регистр не важен
    assert letter_number(" bx-001/26 ") == letter_number("вх-001/26") == "ВХ-001/26"  # выданные раньше — прежний вид
    assert letter_number("BХ-001/26") == "ВХ-001/26"  # латинская B, кириллическая Х — прежний вид


async def test_letters_without_a_number_are_not_duplicates(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    for number in ("б/н", "Б/Н", "-", "без номера"):
        response = await register(
            client, staff["registrar"], SUPPLIER, sender_ref={"number": number, "date": "2026-10-20"}
        )
        assert response.status_code == 201, (number, response.text)


async def test_mark_duplicate_keeps_the_key_only_if_it_is_the_originals_own(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    """Оригинал без исх. №, копия — с номером: после «Это дубль» ключ копии оригиналу не переходит, и письмо с полями
    копии регистрируется (а не упирается в индекс навсегда)."""
    registrar = staff["registrar"]
    original = (await register(client, registrar, SUPPLIER, sender_ref=None)).json()
    copy = (await register(client, registrar, SUPPLIER)).json()
    assert (await mark(client, registrar, copy["id"], original_number=" in-001/26 ")).status_code == 200
    again = await register(client, registrar, SUPPLIER)
    assert again.status_code == 201, again.text

    # Ключ в индексе у письма с другими полями (так было до исправления): 409 с владельцем; `force` — без ключа.
    async with container.session_factory() as session, session.begin():
        await session.execute(text("UPDATE letters SET dedup_key = NULL WHERE id = :id"), {"id": again.json()["id"]})
        key = exact_key("301234567", None, None, "12/45", date(2026, 10, 20))
        await session.execute(
            text("UPDATE letters SET dedup_key = :k WHERE id = :id"), {"k": key, "id": original["id"]}
        )
        await session.execute(
            text("UPDATE letters SET status = 'duplicate' WHERE id = :id"), {"id": again.json()["id"]}
        )
    blocked = await register(client, registrar, SUPPLIER)
    assert_error(blocked, 409, "CONFLICT", reason="duplicate_letter")
    assert blocked.json()["details"]["duplicate"]["number"] == original["number"]
    assert await check(client, registrar, sender=SUPPLIER["sender"], sender_ref=SUPPLIER["sender_ref"]) == []
    forced = await register(client, registrar, SUPPLIER, force=True, force_reason="Другое письмо")
    assert forced.status_code == 201, forced.text


async def test_a_letter_with_duplicates_cannot_become_a_duplicate(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    registrar = staff["registrar"]
    first = (await register(client, registrar, SUPPLIER)).json()
    second = (await register(client, registrar, SUPPLIER, force=True, force_reason="Тест")).json()
    third = (await register(client, registrar, SUPPLIER, sender_ref={"number": "99", "date": "2026-10-20"})).json()
    assert (await mark(client, registrar, second["id"], original_number=first["number"])).status_code == 200
    chained = await mark(client, registrar, first["id"], original_number=third["number"])
    assert_error(chained, 422, "VALIDATION_FAILED")
    assert chained.json()["details"]["fields"][0]["message"] == "letter_has_duplicates"
