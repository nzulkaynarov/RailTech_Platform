"""СОТР-1: полномочие из «Прав подписи» работает без раздела регистрации писем (pg).

Держатель полномочия на «исходящее письмо» и выбранный подписант видят переданный на подпись черновик, получают задачу
«Подписать» и подписывают; «Подписать некому» не показывается, пока есть вправе подписать. Чужие по-прежнему черновик
не открывают.
"""

from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person
from tests.test_document_notices import authorise, hand_over, notices
from tests.test_letterhead_letters import PAIR, deliver_letterhead, letter_json
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
