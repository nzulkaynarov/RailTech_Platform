"""ЕД-6: подписант письма выбирается из держателей права подписи; задача «Подписать» уходит выбранному."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app import clock
from app.container import Container
from tests.domain import Person
from tests.test_letterhead_letters import PAIR, deliver_letterhead
from tests.test_reply_path import reply_draft, tasks_of
from tests.test_sc9_signing import card, grant, hand_over

pytestmark = pytest.mark.pg

DIRECTOR, REGISTRAR = 3, 4


async def signer_ids(client: httpx.AsyncClient, who: Person) -> list[int]:
    found = await client.get("/api/v1/employees/signers", headers=who.headers)
    assert found.status_code == 200, found.text
    return [item["crm_user_id"] for item in found.json()["items"]]


def with_signer(signer: int, **letter: Any) -> dict[str, Any]:
    return {"signer_crm_user_id": signer, **letter}


async def draft_with(client: httpx.AsyncClient, who: Person, signer: int, **letter: Any) -> dict[str, Any]:
    from tests.test_letterhead_letters import letter_json

    body = letter_json()
    body["letter"].update(with_signer(signer, **letter))
    created = await client.post("/api/v1/documents", json=body, headers=who.headers)
    assert created.status_code == 201, created.text
    found: dict[str, Any] = created.json()
    return found


async def test_signers_list_is_the_holders_of_a_letter_authority(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    assert await signer_ids(client, staff["manager"]) == []
    await grant(client, staff, "director")
    await grant(client, staff, "registrar", kinds=["memo"])  # право на другой вид — не подписант письма
    assert await signer_ids(client, staff["manager"]) == [DIRECTOR]
    await grant(client, staff, "registrar")
    assert sorted(await signer_ids(client, staff["manager"])) == [DIRECTOR, REGISTRAR]


async def test_a_signer_without_the_right_is_refused(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    from tests.test_letterhead_letters import letter_json

    await grant(client, staff, "director")
    body = letter_json()
    body["letter"]["signer_crm_user_id"] = staff["accountant"].id
    refused = await client.post("/api/v1/documents", json=body, headers=staff["manager"].headers)
    assert refused.status_code == 422, refused.text
    assert "no_signing_right" in refused.text


async def test_signature_task_goes_to_the_chosen_signer_not_the_computed_one(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await grant(client, staff, "director")
    await grant(client, staff, "registrar")
    plain = await reply_draft(client, staff["manager"], None)  # без выбора — подбирает реестр
    default = (await card(client, staff["manager"], plain["id"]))["signing"]["signer"]["crm_user_id"]
    other = REGISTRAR if default == DIRECTOR else DIRECTOR
    names = {DIRECTOR: staff["director"].name, REGISTRAR: staff["registrar"].name}
    await hand_over(client, staff["manager"], plain["id"])
    chosen = await draft_with(client, staff["manager"], other)
    assert chosen["letter"]["signer_crm_user_id"] == other
    assert chosen["letter"]["signatory_name"] == names[other]  # имя — из справочника
    await hand_over(client, staff["manager"], chosen["id"])

    tasks = {
        uid: [t["document_id"] for t in (await tasks_of(client, staff[who]))["signatures"]]
        for uid, who in ((DIRECTOR, "director"), (REGISTRAR, "registrar"))
    }
    assert tasks[default] == [plain["id"]]  # старое поведение у письма без выбора
    assert tasks[other] == [chosen["id"]]  # выбранному — только его письмо


async def test_chosen_signer_absent_task_goes_to_the_deputy(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await grant(client, staff, "director")
    await grant(client, staff, "registrar")
    today = clock.company_date(clock.now())
    async with container.session_factory() as session, session.begin():
        await session.execute(
            text("UPDATE employees SET deputy_crm_user_id = 3, deputy_from = :a, deputy_to = :b WHERE crm_user_id = 4"),
            {"a": today - timedelta(days=1), "b": today + timedelta(days=3)},
        )
    doc = await draft_with(client, staff["manager"], REGISTRAR)
    await hand_over(client, staff["manager"], doc["id"])
    assert (await tasks_of(client, staff["registrar"]))["signatures"] == []
    [task] = (await tasks_of(client, staff["director"]))["signatures"]
    assert task["acting_for"]["crm_user_id"] == REGISTRAR


async def test_chosen_signer_who_lost_the_right_does_not_leave_the_letter_without_a_signer(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await grant(client, staff, "director")
    await grant(client, staff, "registrar")
    doc = await draft_with(client, staff["manager"], REGISTRAR)
    authorities = (await client.get("/api/v1/signing/authorities", headers=staff["admin"].headers)).json()["items"]
    [mine] = [a for a in authorities if a["holder"]["crm_user_id"] == REGISTRAR]
    revoked = await client.post(
        f"/api/v1/signing/authorities/{mine['id']}/revoke", json={"reason": "уволен"}, headers=staff["admin"].headers
    )
    assert revoked.status_code == 200, revoked.text
    await hand_over(client, staff["manager"], doc["id"])
    assert len((await tasks_of(client, staff["director"]))["signatures"]) == 1


async def test_position_for_acting_signer_is_kept_on_the_document_after_signing(
    client: httpx.AsyncClient,
    staff: dict[str, Person],
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)
    await deliver_letterhead(client, container)
    await grant(client, staff, "director")
    doc = await draft_with(client, staff["manager"], DIRECTOR, signatory_position="И. о. генерального директора")
    assert doc["letter"]["signatory_position"] == "И. о. генерального директора"
    await hand_over(client, staff["manager"], doc["id"])
    signed = await client.post(
        f"/api/v1/documents/{doc['id']}/sign", json={"send": False}, headers=staff["director"].headers
    )
    assert signed.status_code == 200, signed.text
    assert (await card(client, staff["director"], doc["id"]))["letter"]["signatory_position"] == (
        "И. о. генерального директора"
    )
    listed = (await client.get("/api/v1/employees", headers=staff["admin"].headers)).json()["items"]
    [entry] = [e for e in listed if e["crm_user_id"] == DIRECTOR]
    assert entry["position"] != "И. о. генерального директора"  # справочник не менялся
