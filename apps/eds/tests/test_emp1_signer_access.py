"""СОТР-1: полномочие из «Прав подписи» работает без раздела регистрации писем (pg).

Держатель полномочия на «исходящее письмо» и выбранный подписант видят переданный на подпись черновик, получают задачу
«Подписать» и подписывают; «Подписать некому» не показывается, пока есть вправе подписать. Чужие по-прежнему черновик
не открывают.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.container import Container
from tests.conftest import FakeClock
from tests.domain import Person
from tests.test_document_notices import authorise, hand_over, notices
from tests.test_files import upload
from tests.test_letterhead_letters import PAIR, StubRenderer, deliver_letterhead, letter_json, run
from tests.test_reply_path import tasks_of
from tests.test_sc9_signing import card

pytestmark = pytest.mark.pg

ACCOUNTANT = 6  # letters.read, registry.read, memos.create…: без letters.register и memos.approve


async def get(client: httpx.AsyncClient, who: Person, document_id: str) -> httpx.Response:
    return await client.get(f"/api/v1/documents/{document_id}", headers=who.headers)


async def test_holder_without_register_opens_the_draft_gets_the_task_and_signs(
    client: httpx.AsyncClient,
    container: Container,
    staff: dict[str, Person],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)
    await deliver_letterhead(client, container)
    await authorise(client, staff, crm_user_id=ACCOUNTANT)
    assert "letters.register" not in staff["accountant"].permissions
    assert "memos.approve" not in staff["accountant"].permissions
    doc = await hand_over(client, staff["manager"])

    # Signer is resolved, nobody is told «Подписать некому», the holder gets the request.
    [notice] = await notices(container)
    assert (notice["kind"], notice["recipients"]) == ("letter_sign_requested", [ACCOUNTANT])
    assert [t["document_id"] for t in (await tasks_of(client, staff["accountant"]))["signatures"]] == [doc["id"]]

    opened = await card(client, staff["accountant"], doc["id"])
    assert opened["signing"]["can_sign"] is True and opened["signing"]["signer"]["crm_user_id"] == ACCOUNTANT

    signed = await client.post(
        f"/api/v1/documents/{doc['id']}/sign", json={"send": False}, headers=staff["accountant"].headers
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "sent" and signed.json()["signed_by"]["crm_user_id"] == ACCOUNTANT


async def test_chosen_signer_without_register_opens_the_handed_draft(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT)
    await authorise(client, staff)  # и директор тоже вправе
    body = letter_json()
    body["letter"]["signer_crm_user_id"] = ACCOUNTANT
    created = await client.post("/api/v1/documents", json=body, headers=staff["manager"].headers)
    assert created.status_code == 201, created.text
    doc = created.json()
    handed = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    assert handed.status_code == 200, handed.text
    assert (await get(client, staff["accountant"], doc["id"])).status_code == 200
    assert (await card(client, staff["accountant"], doc["id"]))["signing"]["signer"]["crm_user_id"] == ACCOUNTANT


async def test_others_still_cannot_open_the_draft(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT)
    doc = await hand_over(client, staff["manager"])
    for name in ("supplier", "engineer", "lawyer", "nobody"):  # без полномочия, без registry.read-обхода для черновика
        found = await get(client, staff[name], doc["id"])
        assert found.status_code in (403, 404), (name, found.status_code)
    # Без полномочия подписать нельзя: 404 (письма не видно) или 403.
    refused = await client.post(f"/api/v1/documents/{doc['id']}/sign", headers=staff["supplier"].headers)
    assert refused.status_code in (403, 404), refused.text


async def test_holder_cannot_open_a_draft_that_is_not_handed_over(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT)
    created = await client.post("/api/v1/documents", json=letter_json(), headers=staff["manager"].headers)
    assert created.status_code == 201, created.text
    doc: dict[str, Any] = created.json()
    assert (await get(client, staff["accountant"], doc["id"])).status_code == 404  # черновик ещё у автора


async def test_revoked_holder_loses_the_handed_draft(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT)
    authorities = (await client.get("/api/v1/signing/authorities", headers=staff["admin"].headers)).json()["items"]
    mine = next(a for a in authorities if a["holder"]["crm_user_id"] == ACCOUNTANT)
    revoked = await client.post(
        f"/api/v1/signing/authorities/{mine['id']}/revoke", json={"reason": "уволен"}, headers=staff["admin"].headers
    )
    assert revoked.status_code == 200, revoked.text
    doc = await hand_over(client, staff["manager"])
    assert (await get(client, staff["accountant"], doc["id"])).status_code == 404


async def test_attachments_of_the_handed_draft_open_for_the_signer_only(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT)
    ref = (await upload(client, staff["manager"])).json()
    body = letter_json()
    body["file_ids"] = [ref["id"]]
    created = await client.post("/api/v1/documents", json=body, headers=staff["manager"].headers)
    assert created.status_code == 201, created.text
    doc = created.json()
    url = f"/api/v1/files/{ref['id']}"
    # Not handed over yet: the holder cannot open the file.
    assert (await client.get(url, headers=staff["accountant"].headers)).status_code == 404
    handed = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    assert handed.status_code == 200, handed.text
    assert (await client.get(url, headers=staff["accountant"].headers)).status_code == 200
    for name in ("supplier", "engineer", "lawyer"):
        assert (await client.get(url, headers=staff[name].headers)).status_code == 404, name


async def handed(client: httpx.AsyncClient, staff: dict[str, Person], **changes: Any) -> dict[str, Any]:
    created = await client.post("/api/v1/documents", json=letter_json(**changes), headers=staff["manager"].headers)
    assert created.status_code == 201, created.text
    doc: dict[str, Any] = created.json()
    done = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    assert done.status_code == 200, done.text
    return doc


async def test_revoked_after_the_choice_the_signer_loses_the_draft(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT)
    body = letter_json()
    body["letter"]["signer_crm_user_id"] = ACCOUNTANT
    created = await client.post("/api/v1/documents", json=body, headers=staff["manager"].headers)
    doc = created.json()
    await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    assert (await get(client, staff["accountant"], doc["id"])).status_code == 200
    authorities = (await client.get("/api/v1/signing/authorities", headers=staff["admin"].headers)).json()["items"]
    mine = next(a for a in authorities if a["holder"]["crm_user_id"] == ACCOUNTANT)
    revoked = await client.post(
        f"/api/v1/signing/authorities/{mine['id']}/revoke", json={"reason": "уволен"}, headers=staff["admin"].headers
    )
    assert revoked.status_code == 200, revoked.text
    assert (await get(client, staff["accountant"], doc["id"])).status_code == 404  # выбранный, но уже не держатель


async def test_authority_not_started_yet_gives_no_access(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT, valid_from="2026-10-27")  # завтра по часам теста
    doc = await handed(client, staff)
    assert (await get(client, staff["accountant"], doc["id"])).status_code == 404


async def test_amount_over_the_limit_gives_no_access_and_within_it_does(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT, limit_amount="1000000.00", limit_currency="UZS")
    over = await handed(client, staff, amount={"amount": "1500000.00", "currency": "UZS"})
    within = await handed(client, staff, amount={"amount": "900000.00", "currency": "UZS"})
    other_currency = await handed(client, staff, amount={"amount": "10.00", "currency": "USD"})
    assert (await get(client, staff["accountant"], over["id"])).status_code == 404
    assert (await get(client, staff["accountant"], within["id"])).status_code == 200
    assert (await get(client, staff["accountant"], other_currency["id"])).status_code == 404


async def test_valid_to_boundary_is_counted_in_company_time(
    client: httpx.AsyncClient, staff: dict[str, Person], clock: FakeClock
) -> None:
    await authorise(client, staff, crm_user_id=ACCOUNTANT, valid_to="2026-10-26")
    doc = await handed(client, staff)
    clock.set(datetime(2026, 10, 26, 18, 0, tzinfo=UTC))  # 23:00 в Ташкенте: последний день ещё идёт
    assert (await get(client, staff["accountant"], doc["id"])).status_code == 200
    clock.set(datetime(2026, 10, 26, 19, 30, tzinfo=UTC))  # 00:30 следующего дня в Ташкенте
    assert (await get(client, staff["accountant"], doc["id"])).status_code == 404


async def test_valid_signer_opens_the_draft_pdf_and_others_do_not(
    client: httpx.AsyncClient,
    container: Container,
    staff: dict[str, Person],
    deferred: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)
    await deliver_letterhead(client, container)
    await authorise(client, staff, crm_user_id=ACCOUNTANT)
    doc = await handed(client, staff)
    built = await client.post(f"/api/v1/documents/{doc['id']}/pdf", headers=staff["manager"].headers)
    assert built.status_code == 202, built.text
    assert await run(container, StubRenderer(), deferred[0]) == "ready"
    url = f"/api/v1/documents/{doc['id']}/pdf/file"
    assert (await client.get(url, headers=staff["accountant"].headers)).status_code == 200
    assert (await client.get(url, headers=staff["supplier"].headers)).status_code in (403, 404)
