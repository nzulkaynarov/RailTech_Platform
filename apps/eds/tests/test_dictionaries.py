"""Справочники документооборота как данные (EDS-REG, pg): стартовые значения из миграции, добавить, переименовать,
скрыть, удалить неиспользованное, порядок; регистрация письма берёт значения из справочника; права администратора."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.container import Container
from app.models import JournalEntry
from tests.domain import Person, validate
from tests.test_api_auth import assert_error
from tests.test_letter_registration import TAX_NOTICE, register

pytestmark = pytest.mark.pg

BASE = "/api/v1/dictionaries"


async def items(client: httpx.AsyncClient, who: Person, kind: str, **params: Any) -> list[dict[str, Any]]:
    response = await client.get(f"{BASE}/{kind}", params=params, headers=who.headers)
    assert response.status_code == 200, response.text
    validate("DictionaryItemList", response.json())
    result: list[dict[str, Any]] = response.json()["items"]
    return result


async def test_catalog_and_starter_values_repeat_the_former_code(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    catalog = await client.get(BASE, headers=staff["admin"].headers)
    assert catalog.status_code == 200, catalog.text
    validate("DictionaryList", catalog.json())
    kinds = {d["kind"]: d for d in catalog.json()["items"]}
    assert set(kinds) == {"letter-kinds", "receipt-methods"}
    assert [a["key"] for a in kinds["letter-kinds"]["attrs"]] == ["urgent", "due_days"]
    assert kinds["receipt-methods"]["attrs"] == []

    kinds_list = await items(client, staff["registrar"], "letter-kinds")
    assert [i["code"] for i in kinds_list] == ["tax_notice", "bank", "supplier", "government", "counterparty", "other"]
    assert kinds_list[0]["attrs"] == {"urgent": True, "due_days": 3}
    assert kinds_list[1]["attrs"] == {"urgent": False, "due_days": None}
    assert all(i["used"] is None for i in kinds_list)  # без include_hidden не считается
    methods = await items(client, staff["registrar"], "receipt-methods")
    assert [i["code"] for i in methods] == ["paper", "post", "taxpayer_cabinet", "courier", "email"]
    assert methods[2]["name"]["ru"] == "Кабинет налогоплательщика my.soliq"

    # Прежний ресурс видов документа отдаёт то же из таблицы.
    legacy = (await client.get("/api/v1/letter-kinds", headers=staff["registrar"].headers)).json()
    validate("LetterKindList", legacy)
    assert legacy["items"][0] == {
        "code": "tax_notice",
        "name": kinds_list[0]["name"],
        "urgent": True,
        "due_days": 3,
    }


async def test_admin_adds_a_kind_and_the_registrar_uses_it(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    created = await client.post(
        f"{BASE}/letter-kinds",
        json={"name": {"ru": "Претензия покупателя", "en": ""}, "attrs": {"urgent": True, "due_days": 7}},
        headers=staff["admin"].headers,
    )
    assert created.status_code == 201, created.text
    validate("DictionaryItem", created.json())
    item = created.json()
    assert item["code"] == "pretenziya_pokupatelya"
    assert (item["position"], item["active"], item["used"]) == (70, True, False)
    assert item["name"] == {"ru": "Претензия покупателя", "uz": "", "en": ""}

    letter = await register(client, staff["registrar"], kind=item["code"], urgent=False, document_due=None)
    assert letter.status_code == 201, letter.text
    body = letter.json()
    assert (body["kind"], body["urgent"]) == ("pretenziya_pokupatelya", True)  # «срочный» — из справочника
    # Срок вида (7 дней) — подсказка резолюции без срока по документу.
    assert body["suggested_due"] is not None

    async with container.session_factory() as session:
        actions = (await session.execute(select(JournalEntry.action, JournalEntry.comment))).all()
    assert ("dictionary.created", "letter-kinds: pretenziya_pokupatelya") in actions

    # Второе такое же название — конфликт; код по английскому названию.
    again = await client.post(
        f"{BASE}/letter-kinds", json={"name": {"ru": "претензия покупателя "}}, headers=staff["admin"].headers
    )
    assert_error(again, 409, "CONFLICT")
    assert again.json()["details"]["reason"] == "name_taken"
    english = await client.post(
        f"{BASE}/receipt-methods",
        json={"name": {"ru": "Фельдъегерская связь", "uz": "Feldyeger", "en": "Courier service"}},
        headers=staff["admin"].headers,
    )
    assert english.status_code == 201, english.text
    assert english.json()["code"] == "courier_service"
    # Новый способ получения — без CHECK в базе: регистрация проходит.
    by_new = await register(client, staff["registrar"], receipt_method="courier_service", sender_ref={"number": "9"})
    assert by_new.status_code == 201, by_new.text
    assert by_new.json()["receipt_method"] == "courier_service"


async def test_attrs_are_checked_by_the_dictionary_kind(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    headers = staff["admin"].headers
    wrong = await client.post(
        f"{BASE}/letter-kinds", json={"name": {"ru": "Счёт"}, "attrs": {"due_days": 0, "color": 1}}, headers=headers
    )
    assert_error(wrong, 422, "VALIDATION_FAILED")
    fields = {f["field"]: f["message"] for f in wrong.json()["details"]["fields"]}
    assert fields == {"attrs.due_days": "invalid_value", "attrs.color": "unknown_attr"}
    flag = await client.post(
        f"{BASE}/receipt-methods", json={"name": {"ru": "Факс"}, "attrs": {"urgent": True}}, headers=headers
    )
    assert_error(flag, 422, "VALIDATION_FAILED")
    missing = await client.get(f"{BASE}/currencies", headers=headers)
    assert_error(missing, 404, "NOT_FOUND")
    rename = await client.patch(
        f"{BASE}/letter-kinds/bank",
        json={"name": {"ru": "Письмо банка или МФО", "uz": "Bank xati", "en": "Bank letter"}, "attrs": {"due_days": 5}},
        headers=headers,
    )
    assert rename.status_code == 200, rename.text
    assert rename.json()["attrs"] == {"urgent": False, "due_days": 5}
    assert rename.json()["code"] == "bank"


async def test_used_value_is_hidden_not_deleted_and_old_letters_keep_it(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    headers = staff["admin"].headers
    letter = (await register(client, staff["registrar"], kind="bank", receipt_method="post")).json()

    listed = await items(client, staff["admin"], "letter-kinds", include_hidden="true")
    used = {i["code"]: i["used"] for i in listed}
    assert used["bank"] is True and used["supplier"] is False

    denied = await client.delete(f"{BASE}/letter-kinds/bank", headers=headers)
    assert_error(denied, 409, "CONFLICT")
    assert denied.json()["details"]["reason"] == "value_in_use"

    hidden = await client.patch(f"{BASE}/letter-kinds/bank", json={"active": False}, headers=headers)
    assert hidden.status_code == 200, hidden.text
    assert (hidden.json()["active"], hidden.json()["used"]) == (False, True)
    assert "bank" not in [i["code"] for i in await items(client, staff["registrar"], "letter-kinds")]
    assert "bank" in [i["code"] for i in await items(client, staff["registrar"], "letter-kinds", include_hidden="true")]
    legacy = (await client.get("/api/v1/letter-kinds", headers=staff["registrar"].headers)).json()
    assert "bank" not in [i["code"] for i in legacy["items"]]

    # Скрытым видом новое письмо не зарегистрировать; старое показывает свой код как был.
    refused = await register(client, staff["registrar"], kind="bank", sender_ref={"number": "2"})
    assert_error(refused, 422, "VALIDATION_FAILED")
    assert refused.json()["details"]["fields"][0] == {"field": "kind", "message": "unknown_kind", "type": "value_error"}
    old = (await client.get(f"/api/v1/letters/{letter['id']}", headers=staff["registrar"].headers)).json()
    assert old["kind"] == "bank"

    await client.patch(f"{BASE}/receipt-methods/courier", json={"active": False}, headers=headers)
    no_method = await register(client, staff["registrar"], receipt_method="courier", sender_ref={"number": "3"})
    assert no_method.json()["details"]["fields"][0]["message"] == "unknown_method"

    # Неиспользованное удаляется.
    removed = await client.delete(f"{BASE}/letter-kinds/supplier", headers=headers)
    assert removed.status_code == 204, removed.text
    assert "supplier" not in [
        i["code"] for i in await items(client, staff["admin"], "letter-kinds", include_hidden="true")
    ]


async def test_order_takes_the_full_list_of_codes(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    headers = staff["admin"].headers
    codes = ["email", "paper", "post", "taxpayer_cabinet", "courier"]
    ordered = await client.put(f"{BASE}/receipt-methods/order", json={"codes": codes}, headers=headers)
    assert ordered.status_code == 200, ordered.text
    validate("DictionaryItemList", ordered.json())
    assert [i["code"] for i in await items(client, staff["registrar"], "receipt-methods")] == codes
    partial = await client.put(f"{BASE}/receipt-methods/order", json={"codes": codes[:3]}, headers=headers)
    assert_error(partial, 422, "VALIDATION_FAILED")
    doubled = await client.put(f"{BASE}/receipt-methods/order", json={"codes": [*codes[:4], "email"]}, headers=headers)
    assert_error(doubled, 422, "VALIDATION_FAILED")


async def test_letters_journal_filters_by_kind(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    await register(client, staff["registrar"])
    bank = (await register(client, staff["registrar"], kind="bank", sender_ref={"number": "B-1"})).json()
    found = await client.get("/api/v1/letters", params={"kind": "bank"}, headers=staff["registrar"].headers)
    assert found.status_code == 200, found.text
    assert [i["number"] for i in found.json()["items"]] == [bank["number"]]


async def test_only_the_admin_changes_dictionaries(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    for who in ("registrar", "director", "manager"):
        headers = staff[who].headers
        assert_error(
            await client.post(f"{BASE}/letter-kinds", json={"name": {"ru": "X"}}, headers=headers),
            403,
            "FORBIDDEN",
            permission="bus.manage",
        )
        assert_error(
            await client.patch(f"{BASE}/letter-kinds/bank", json={"active": False}, headers=headers), 403, "FORBIDDEN"
        )
        assert_error(await client.delete(f"{BASE}/letter-kinds/other", headers=headers), 403, "FORBIDDEN")
        assert_error(
            await client.put(f"{BASE}/letter-kinds/order", json={"codes": ["bank"]}, headers=headers), 403, "FORBIDDEN"
        )
    # Читать может тот, кто работает с письмами, и администратор; снабженец без писем — нет.
    assert (await client.get(f"{BASE}/letter-kinds", headers=staff["admin"].headers)).status_code == 200
    assert (await client.get(f"{BASE}/letter-kinds", headers=staff["manager"].headers)).status_code == 200
    assert_error(await client.get(BASE, headers=staff["supplier"].headers), 403, "FORBIDDEN")


async def test_tax_notice_still_urgent_from_the_seeded_dictionary(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    letter = await register(client, staff["registrar"], **{**TAX_NOTICE, "urgent": False})
    assert letter.json()["urgent"] is True
