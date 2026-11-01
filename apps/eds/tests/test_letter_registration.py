"""Регистрация входящего делопроизводителем (P8, SPEC-v3 §3.2a п. 1, pg): карточка, справочник видов, «срочно» для ГНК,
связь с ВХ и ИСХ, проверка дубля, регистрация без права резолюции."""

from typing import Any

import httpx
import pytest

from tests.domain import Person, validate
from tests.test_api_auth import assert_error

pytestmark = pytest.mark.pg

TAX_NOTICE: dict[str, Any] = {
    "kind": "tax_notice",
    "receipt_method": "taxpayer_cabinet",
    "subject": "Требование о представлении пояснений по НДС за III квартал",
    "sender": {"name": "ГНИ Мирабадского района"},
    "sender_ref": {"number": "04-12/3456", "date": "2026-10-28"},
    "received_at": "2026-10-29",
    "signed_by": "Начальник инспекции А. Каримов",
    "document_due": "2026-11-05",
}


async def register(client: httpx.AsyncClient, who: Person, **body: Any) -> httpx.Response:
    return await client.post("/api/v1/letters", json={**TAX_NOTICE, **body}, headers=who.headers)


async def test_letter_kinds_are_the_starter_dictionary(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    response = await client.get("/api/v1/letter-kinds", headers=staff["registrar"].headers)
    assert response.status_code == 200, response.text
    body = response.json()
    validate("LetterKindList", body)
    codes = [item["code"] for item in body["items"]]
    assert codes == ["tax_notice", "bank", "supplier", "government", "counterparty", "other"]
    urgent = {item["code"] for item in body["items"] if item["urgent"]}
    assert urgent == {"tax_notice"}
    assert body["items"][0]["name"]["ru"] == "Требование или уведомление ГНК"


async def test_registrar_registers_a_tax_notice_urgent_without_summary(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    response = await register(client, staff["registrar"], urgent=False)
    assert response.status_code == 201, response.text
    letter = response.json()
    validate("Letter", letter)
    assert letter["number"] == "ВХ-001/26"
    assert letter["status"] == "awaiting_resolution"
    assert letter["urgent"] is True  # вид «Требование ГНК» ставит «срочно» сам
    assert letter["summary"] == TAX_NOTICE["subject"]  # краткое содержание не задано — тема
    assert (letter["kind"], letter["receipt_method"]) == ("tax_notice", "taxpayer_cabinet")
    assert (letter["signed_by"], letter["document_due"]) == ("Начальник инспекции А. Каримов", "2026-11-05")
    assert letter["addressee"]["crm_user_id"] == 3  # директор по умолчанию
    assert letter["related"] is None

    listed = (await client.get("/api/v1/letters", headers=staff["registrar"].headers)).json()
    assert listed["items"][0]["kind"] == "tax_notice"

    # Резолюцию делопроизводитель не накладывает (SPEC-v3 §3.2a «Права»).
    denied = await client.post(
        f"/api/v1/letters/{letter['id']}/resolution",
        json={"text": "В работу", "assignees": [{"crm_user_id": 11, "zone": "goods"}], "due": "2026-11-04"},
        headers=staff["registrar"].headers,
    )
    assert_error(denied, 403, "FORBIDDEN", permission="letters.resolve")


async def test_unknown_kind_and_receipt_method_are_rejected(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    unknown = await register(client, staff["registrar"], kind="lottery")
    assert_error(unknown, 422, "VALIDATION_FAILED")
    assert {"field": "kind", "message": "unknown_kind", "type": "value_error"} in unknown.json()["details"]["fields"]
    assert_error(await register(client, staff["registrar"], receipt_method="pigeon"), 422, "VALIDATION_FAILED")


async def test_related_number_links_a_previous_letter_or_our_outgoing(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    first = (await register(client, staff["registrar"])).json()
    second = await register(
        client, staff["registrar"], related_number=first["number"], sender_ref={"number": "04-12/3500"}
    )
    assert second.status_code == 201, second.text
    assert second.json()["related"] == {"kind": "letter_in", "id": first["id"], "number": "ВХ-001/26"}

    outgoing = await client.post(
        "/api/v1/documents",
        json={"kind": "letter_out", "subject": "Пояснения", "text": "Направляем", "recipient": {"name": "ГНИ"}},
        headers=staff["registrar"].headers,
    )
    sent = await client.post(f"/api/v1/documents/{outgoing.json()['id']}/submit", headers=staff["registrar"].headers)
    number = sent.json()["number"]
    third = await register(client, staff["registrar"], related_number=number, sender_ref={"number": "04-12/3600"})
    assert third.status_code == 201, third.text
    assert third.json()["related"]["kind"] == "letter_out"
    assert third.json()["related"]["number"] == number

    missing = await register(client, staff["registrar"], related_number="ВХ-999/26")
    assert_error(missing, 422, "VALIDATION_FAILED")
    assert missing.json()["details"]["fields"][0]["field"] == "related_number"
    assert missing.json()["details"]["fields"][0]["message"] == "not_found"


async def test_duplicate_check_by_sender_and_outgoing_number(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    letter = (await register(client, staff["registrar"])).json()
    headers = staff["registrar"].headers

    async def check(**params: Any) -> list[str]:
        response = await client.get("/api/v1/letter-duplicates", params=params, headers=headers)
        assert response.status_code == 200, response.text
        validate("LetterDuplicateList", response.json())
        return [item["number"] for item in response.json()["items"]]

    # Тот же корреспондент без учёта регистра и лишних пробелов, тот же исх. №.
    assert await check(ref_number=" 04-12/3456 ", sender_name="гни  мирабадского района") == [letter["number"]]
    assert await check(ref_number="04-12/0000", sender_name="ГНИ Мирабадского района") == []
    assert await check(ref_number="04-12/3456", sender_name="Другой отправитель") == []
    assert await check(ref_number="04-12/3456") == []  # без корреспондента — не дубль

    by_client = await register(
        client, staff["registrar"], sender={"name": None}, links={"crm_client_id": 42}, sender_ref={"number": "77"}
    )
    assert by_client.status_code == 201, by_client.text
    assert await check(ref_number="77", crm_client_id=42) == [by_client.json()["number"]]

    # Дубль — предупреждение, не запрет: вторая регистрация проходит.
    again = await register(client, staff["registrar"])
    assert again.status_code == 201
    assert len(await check(ref_number="04-12/3456", sender_name="ГНИ Мирабадского района")) == 2


async def test_kinds_and_duplicates_need_reading_or_registering_letters(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    for who in ("supplier", "nobody"):
        denied = await client.get("/api/v1/letter-kinds", headers=staff[who].headers)
        assert_error(denied, 403, "FORBIDDEN")
    allowed = await client.get("/api/v1/letter-kinds", headers=staff["manager"].headers)
    assert allowed.status_code == 200
