"""Реестр полномочий подписи (pg, API): выдача с основанием и сроком, инварианты на сервере и в базе, список и
«истекает через N дней», изменение, отзыв, файл основания, журнал, справочник видов, подсказка первого запуска
(SIGN-2, ADR-0024 п. 1, 8)."""

import asyncio
import uuid
from datetime import date, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.container import Container
from tests.conftest import FakeClock
from tests.domain import Person, validate
from tests.helpers import seed_employee

pytestmark = pytest.mark.pg

URL = "/api/v1/signing/authorities"
PDF = b"%PDF-1.4\n%test\n"
CHARTER: dict[str, Any] = {
    "crm_user_id": 3,
    "kinds": ["letter_out", "contract"],
    "basis": "charter",
    "valid_from": "2026-01-01",
}
POA: dict[str, Any] = {
    "crm_user_id": 5,
    "kinds": ["letter_out"],
    "limit_amount": "10000000.00",
    "limit_currency": "UZS",
    "basis": "power_of_attorney",
    "basis_number": "17",
    "basis_date": "2026-03-01",
    "valid_from": "2026-03-01",
    "valid_to": "2027-03-01",
}


async def issue(client: httpx.AsyncClient, admin: Person, **body: Any) -> dict[str, Any]:
    response = await client.post(URL, json=body, headers=admin.headers)
    assert response.status_code == 201, response.text
    validate("SigningAuthorityDetail", response.json())
    return dict(response.json())


def fields(response: httpx.Response) -> set[str]:
    assert response.status_code == 422, response.text
    return {f["field"] for f in response.json()["details"]["fields"]}


# --- права ----------------------------------------------------------------------------------------------------------


async def test_only_the_register_keeper_may_use_the_registry(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    assert (await client.get(URL, headers=staff["director"].headers)).status_code == 403
    assert (await client.post(URL, json=CHARTER, headers=staff["director"].headers)).status_code == 403
    assert (await client.get(URL, headers=staff["nobody"].headers)).status_code == 403
    assert (await client.get(URL, headers=staff["admin"].headers)).status_code == 200


# --- выдача: основание, срок, лимит ------------------------------------------------------------------------------


async def test_charter_is_issued_without_number_and_written_to_the_journal(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    created = await issue(client, staff["admin"], **CHARTER)
    assert created["holder"] == {"crm_user_id": 3, "full_name": "Рустам Директоров"}
    assert (created["status"], created["expires_in_days"], created["limit_amount"]) == ("active", None, None)
    assert [e["action"] for e in created["journal"]] == ["issued"]
    assert created["journal"][0]["by"]["crm_user_id"] == 9
    assert created["journal"][0]["details"]["after"]["kinds"] == ["letter_out", "contract"]


async def test_power_of_attorney_is_issued_with_limit_and_vakolat_link(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    created = await issue(client, staff["admin"], **POA, vakolat_url="https://vakolat.uz/ru/proxy/777")
    assert (created["basis_number"], created["valid_to"], created["limit_amount"]) == (
        "17",
        "2027-03-01",
        "10000000.00",
    )
    assert created["vakolat_url"] == "https://vakolat.uz/ru/proxy/777"


@pytest.mark.parametrize(
    ("change", "bad_field"),
    [
        ({"basis_number": None}, "basis_number"),
        ({"basis_date": None}, "basis_date"),
        ({"valid_to": None}, "valid_to"),
        ({"valid_to": "2029-03-02"}, "valid_to"),
        ({"valid_from": "2026-02-28"}, "valid_from"),
        ({"limit_currency": None}, "limit_currency"),
        ({"vakolat_url": "https://example.com/x"}, "vakolat_url"),
        ({"kinds": ["no_such_kind"]}, "kinds"),
        ({"kinds": ["act", "act"]}, "kinds"),
        ({"crm_user_id": 999}, "crm_user_id"),
    ],
)
async def test_invalid_terms_are_refused_with_the_field_named(
    client: httpx.AsyncClient, staff: dict[str, Person], change: dict[str, Any], bad_field: str
) -> None:
    response = await client.post(URL, json={**POA, **change}, headers=staff["admin"].headers)
    assert bad_field in fields(response)


async def test_three_year_boundary_is_allowed_and_charter_with_number_is_not(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await issue(client, staff["admin"], **{**POA, "valid_to": "2029-03-01"})
    refused = await client.post(URL, json={**CHARTER, "basis_number": "1"}, headers=staff["admin"].headers)
    assert "basis_number" in fields(refused)


async def test_overlapping_authorities_of_one_person_are_allowed(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await issue(client, staff["admin"], **{**CHARTER, "crm_user_id": 5})
    await issue(client, staff["admin"], **POA)
    listing = (await client.get(URL, params={"crm_user_id": 5}, headers=staff["admin"].headers)).json()
    assert len(listing["items"]) == 2


async def test_deactivated_employee_cannot_be_given_authority(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await seed_employee(container, 40, full_name="Уволен Уволенов", is_active=False)
    response = await client.post(URL, json={**CHARTER, "crm_user_id": 40}, headers=staff["admin"].headers)
    assert "crm_user_id" in fields(response)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE signing_authorities SET basis_number = NULL WHERE basis = 'power_of_attorney'",
        "UPDATE signing_authorities SET valid_to = '2029-03-02' WHERE basis = 'power_of_attorney'",
        "UPDATE signing_authorities SET valid_to = NULL WHERE basis = 'power_of_attorney'",
        "UPDATE signing_authorities SET basis_number = '1' WHERE basis = 'charter'",
        "UPDATE signing_authorities SET limit_currency = NULL WHERE limit_amount IS NOT NULL",
        "UPDATE signing_authorities SET valid_to = '2020-01-01'",
        "UPDATE signing_authorities SET kinds = '{}'",
        "UPDATE signing_authorities SET basis = 'verbal'",
    ],
)
async def test_database_refuses_what_the_rules_refuse(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], sql: str
) -> None:
    await issue(client, staff["admin"], **POA)
    await issue(client, staff["admin"], **CHARTER)
    async with container.session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(text(sql))


# --- список и «истекает через N дней» ---------------------------------------------------------------------------------


async def test_list_filters_and_expiry_countdown(
    client: httpx.AsyncClient, staff: dict[str, Person], clock: FakeClock
) -> None:
    clock.set(datetime.fromisoformat("2026-11-05T08:00:00+00:00"))
    admin = staff["admin"]
    charter = await issue(client, admin, **CHARTER)
    soon = await issue(
        client, admin, **{**POA, "basis_date": "2025-11-20", "valid_from": "2025-11-20", "valid_to": "2026-11-20"}
    )
    far = await issue(client, admin, **{**POA, "crm_user_id": 6, "basis_number": "18"})
    ended = await issue(
        client,
        admin,
        **{
            **POA,
            "crm_user_id": 12,
            "basis_number": "19",
            "basis_date": "2025-01-10",
            "valid_from": "2025-01-10",
            "valid_to": "2026-01-10",
        },
    )
    later = await issue(client, admin, **{**CHARTER, "crm_user_id": 11, "valid_from": "2026-12-01"})
    revoked = await issue(client, admin, **{**POA, "crm_user_id": 4, "basis_number": "20"})
    assert (
        await client.post(f"{URL}/{revoked['id']}/revoke", json={"reason": "Уволен"}, headers=admin.headers)
    ).status_code == 200

    async def ids(status: str) -> set[str]:
        response = await client.get(URL, params={"status": status}, headers=admin.headers)
        validate("SigningAuthorityList", response.json())
        return {i["id"] for i in response.json()["items"]}

    assert await ids("active") == {charter["id"], soon["id"], far["id"]}
    assert await ids("expiring") == {soon["id"]}
    assert await ids("inactive") == {ended["id"], later["id"], revoked["id"]}
    assert len(await ids("all")) == 6
    by_id = {i["id"]: i for i in (await client.get(URL, headers=admin.headers)).json()["items"]}
    assert (by_id[soon["id"]]["status"], by_id[soon["id"]]["expires_in_days"]) == ("expiring", 15)
    assert (by_id[far["id"]]["status"], by_id[far["id"]]["expires_in_days"]) == ("active", 116)
    assert (by_id[ended["id"]]["status"], by_id[ended["id"]]["expires_in_days"]) == ("expired", None)
    assert by_id[later["id"]]["status"] == "scheduled"
    assert by_id[revoked["id"]]["status"] == "revoked" and by_id[revoked["id"]]["revoked"]["reason"] == "Уволен"


# --- изменение и отзыв ---------------------------------------------------------------------------------------------


async def test_update_changes_fields_and_writes_before_after_to_the_journal(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    created = await issue(client, staff["admin"], **POA)
    response = await client.patch(
        f"{URL}/{created['id']}",
        json={"limit_amount": "20000000.00", "kinds": ["letter_out", "quote"], "note": "  Расширено  "},
        headers=staff["admin"].headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["limit_amount"], body["kinds"], body["note"]) == ("20000000.00", ["letter_out", "quote"], "Расширено")
    last = body["journal"][-1]
    assert last["action"] == "updated"
    assert last["details"]["changed"]["limit_amount"] == ["10000000.00", "20000000.00"]
    assert "basis" not in last["details"]["changed"]


async def test_update_without_changes_adds_no_journal_row(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    created = await issue(client, staff["admin"], **POA)
    response = await client.patch(
        f"{URL}/{created['id']}", json={"valid_to": "2027-03-01"}, headers=staff["admin"].headers
    )
    assert len(response.json()["journal"]) == 1


async def test_update_is_checked_by_the_same_invariants(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    created = await issue(client, staff["admin"], **POA)
    headers = staff["admin"].headers
    too_long = await client.patch(f"{URL}/{created['id']}", json={"valid_to": "2030-01-01"}, headers=headers)
    assert "valid_to" in fields(too_long)
    cleared = await client.patch(f"{URL}/{created['id']}", json={"basis_number": None}, headers=headers)
    assert "basis_number" in fields(cleared)
    required = await client.patch(f"{URL}/{created['id']}", json={"kinds": None}, headers=headers)
    assert "kinds" in fields(required)
    holder = await client.patch(f"{URL}/{created['id']}", json={"crm_user_id": 6}, headers=headers)
    assert holder.status_code == 422  # держателя не меняют: выдают новое полномочие
    unlimited = await client.patch(
        f"{URL}/{created['id']}", json={"limit_amount": None, "limit_currency": None}, headers=headers
    )
    assert unlimited.json()["limit_amount"] is None


async def test_revoke_needs_a_reason_keeps_history_and_blocks_further_changes(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    created = await issue(client, staff["admin"], **POA)
    path = f"{URL}/{created['id']}"
    headers = staff["admin"].headers
    assert (await client.post(f"{path}/revoke", json={"reason": ""}, headers=headers)).status_code == 422
    revoked = await client.post(f"{path}/revoke", json={"reason": "Доверенность отозвана приказом"}, headers=headers)
    assert revoked.status_code == 200
    body = revoked.json()
    assert body["status"] == "revoked" and body["revoked"]["by"]["crm_user_id"] == 9
    assert [e["action"] for e in body["journal"]] == ["issued", "revoked"]
    assert body["journal"][-1]["comment"] == "Доверенность отозвана приказом"
    again = await client.post(f"{path}/revoke", json={"reason": "Ещё раз"}, headers=headers)
    assert (again.status_code, again.json()["details"]["reason"]) == (409, "revoked")
    edit = await client.patch(path, json={"note": "x"}, headers=headers)
    assert (edit.status_code, edit.json()["details"]["reason"]) == (409, "revoked")
    assert (await client.get(path, headers=headers)).json()["status"] == "revoked"


async def test_two_parallel_revokes_one_wins_and_the_journal_has_one_row(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    created = await issue(client, staff["admin"], **POA)

    async def revoke(n: int) -> httpx.Response:
        return await client.post(
            f"{URL}/{created['id']}/revoke", json={"reason": f"Причина {n}"}, headers=staff["admin"].headers
        )

    results = await asyncio.gather(*(revoke(n) for n in range(10)))
    assert sorted(r.status_code for r in results) == [200] + [409] * 9
    async with container.session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM signing_authority_events WHERE action = 'revoked' AND authority_id = :id"),
                {"id": uuid.UUID(created["id"])},
            )
        ).scalar_one()
    assert rows == 1


async def test_unknown_authority_is_404(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    ghost = "00000000-0000-4000-8000-0000000000ab"
    headers = staff["admin"].headers
    assert (await client.get(f"{URL}/{ghost}", headers=headers)).status_code == 404
    assert (await client.patch(f"{URL}/{ghost}", json={"note": "x"}, headers=headers)).status_code == 404
    assert (await client.post(f"{URL}/{ghost}/revoke", json={"reason": "abc"}, headers=headers)).status_code == 404


# --- файл основания -------------------------------------------------------------------------------------------------


async def upload(client: httpx.AsyncClient, admin: Person, authority_id: str, data: bytes, name: str, mime: str) -> Any:
    return await client.post(
        f"{URL}/{authority_id}/basis-file", files={"file": (name, data, mime)}, headers=admin.headers
    )


async def test_basis_file_is_stored_privately_versioned_and_downloadable(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    created = await issue(client, staff["admin"], **POA)
    first = await upload(client, staff["admin"], created["id"], PDF, "доверенность.pdf", "application/pdf")
    assert first.status_code == 200, first.text
    ref = first.json()["file"]
    assert (ref["name"], ref["version"], ref["content_type"]) == ("доверенность.pdf", 1, "application/pdf")
    second = await upload(client, staff["admin"], created["id"], PDF + b"v2", "доверенность-2.pdf", "application/pdf")
    assert second.json()["file"]["version"] == 2 and second.json()["file"]["id"] == ref["id"]
    assert [e["action"] for e in second.json()["journal"]] == ["issued", "file_replaced", "file_replaced"]

    path = f"{URL}/{created['id']}/basis-file"
    latest = await client.get(path, headers=staff["admin"].headers)
    assert (latest.status_code, latest.content) == (200, PDF + b"v2")
    assert "attachment" in latest.headers["content-disposition"]
    assert (await client.get(path, params={"version": 1}, headers=staff["admin"].headers)).content == PDF
    # приватно: без права, и через общий ресурс файлов тоже (непривязанный файл видит только загрузивший)
    assert (await client.get(path, headers=staff["director"].headers)).status_code == 403
    assert (await client.get(f"/api/v1/files/{ref['id']}", headers=staff["director"].headers)).status_code == 404


async def test_basis_file_rejects_unsupported_content_and_revoked_authority(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    created = await issue(client, staff["admin"], **POA)
    assert (
        await upload(client, staff["admin"], created["id"], b"MZ\x90", "x.pdf", "application/pdf")
    ).status_code == 415
    assert (await client.get(f"{URL}/{created['id']}/basis-file", headers=staff["admin"].headers)).status_code == 404
    await client.post(f"{URL}/{created['id']}/revoke", json={"reason": "Отозвана"}, headers=staff["admin"].headers)
    assert (await upload(client, staff["admin"], created["id"], PDF, "a.pdf", "application/pdf")).status_code == 409


# --- «кто вправе подписать» по HTTP --------------------------------------------------------------------------------


async def test_resolve_endpoint_answers_with_candidates_and_explanation(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await issue(client, staff["admin"], **CHARTER)
    await issue(client, staff["admin"], **POA)
    ask = {"kind": "letter_out", "amount": "50000000.00", "currency": "UZS", "on_date": "2026-11-10"}
    response = await client.get("/api/v1/signing/resolve", params=ask, headers=staff["admin"].headers)
    assert response.status_code == 200, response.text
    body = response.json()
    validate("SigningResolution", body)
    assert [c["signer"]["crm_user_id"] for c in body["candidates"]] == [3]
    assert [r["reason"] for r in body["rejected"]] == ["limit_exceeded"]
    assert any("превышает лимит" in step["text"] for step in body["explanation"])
    small = await client.get(
        "/api/v1/signing/resolve", params={**ask, "amount": "1000.00"}, headers=staff["admin"].headers
    )
    assert [c["signer"]["crm_user_id"] for c in small.json()["candidates"]] == [3, 5]


async def test_resolve_endpoint_validates_the_question(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    headers = staff["admin"].headers
    assert (
        await client.get("/api/v1/signing/resolve", params={"kind": "act", "amount": "5.00"}, headers=headers)
    ).status_code == 422
    assert (await client.get("/api/v1/signing/resolve", params={"kind": "Act!"}, headers=headers)).status_code == 422
    zero = {"kind": "act", "amount": "0.00", "currency": "UZS"}
    assert (await client.get("/api/v1/signing/resolve", params=zero, headers=headers)).status_code == 422
    empty = await client.get("/api/v1/signing/resolve", params={"kind": "act"}, headers=headers)
    assert empty.status_code == 200 and empty.json()["resolved"] is False
    assert empty.json()["explanation"][0]["code"] == "no_authority"


# --- справочник видов -----------------------------------------------------------------------------------------------


async def test_kinds_are_an_open_dictionary_and_a_used_kind_cannot_be_deleted(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    admin = staff["admin"]
    catalog = (await client.get("/api/v1/dictionaries", headers=admin.headers)).json()["items"]
    assert "signing-kinds" in {d["kind"] for d in catalog}
    items = (await client.get("/api/v1/dictionaries/signing-kinds", headers=admin.headers)).json()["items"]
    assert [i["code"] for i in items] == ["letter_out", "quote", "contract", "invoice", "act", "memo"]
    added = await client.post(
        "/api/v1/dictionaries/signing-kinds",
        json={"name": {"ru": "Приказ", "uz": "Buyruq", "en": "Order"}, "attrs": {}},
        headers=admin.headers,
    )
    assert added.status_code == 201, added.text
    code = added.json()["code"]
    await issue(client, admin, **{**CHARTER, "kinds": [code]})
    deleted = await client.delete(f"/api/v1/dictionaries/signing-kinds/{code}", headers=admin.headers)
    assert (deleted.status_code, deleted.json()["details"]["reason"]) == (409, "value_in_use")
    hidden = await client.patch(
        f"/api/v1/dictionaries/signing-kinds/{code}", json={"active": False}, headers=admin.headers
    )
    assert hidden.status_code == 200
    again = await client.post(URL, json={**CHARTER, "kinds": [code]}, headers=admin.headers)
    assert "kinds" in fields(again)  # скрытый вид новым полномочиям не выдают


# --- подсказка первого запуска ---------------------------------------------------------------------------------------


async def test_setup_hint_names_the_director_only_when_the_name_matches_exactly_one_employee(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    headers = staff["admin"].headers
    empty = (await client.get("/api/v1/signing/setup-hint", headers=headers)).json()
    validate("SigningSetupHint", empty)
    assert empty == {"has_authorities": False, "signatory_name": None, "signatory_position": None, "director": None}

    async with container.session_factory() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO letterhead (id, erp_company_id, company_name, inn, legal_address, bank_details, "
                "signatory_name, signatory_position, footer_text, accent_color, font_family, source_time, updated_at) "
                "VALUES (1, 1, 'ООО Пример', '123456789', 'адрес', 'банк', '  рустам  ДИРЕКТОРОВ ', 'Директор', '', "
                "'#112233', 'sans', now(), now())"
            )
        )
    hint = (await client.get("/api/v1/signing/setup-hint", headers=headers)).json()
    assert hint["director"] == {"crm_user_id": 3, "full_name": "Рустам Директоров"}
    assert (hint["signatory_position"], hint["has_authorities"]) == ("Директор", False)

    await seed_employee(container, 41, full_name="Рустам Директоров", email="twin@example.com")
    assert (await client.get("/api/v1/signing/setup-hint", headers=headers)).json()[
        "director"
    ] is None  # двое — не угадываем
    await issue(client, staff["admin"], **CHARTER)
    assert (await client.get("/api/v1/signing/setup-hint", headers=headers)).json()["has_authorities"] is True


def test_today_is_the_company_date() -> None:
    from app.services import signing_registry

    assert isinstance(signing_registry.today(), date)
