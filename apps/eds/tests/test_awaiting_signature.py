"""СЦ-8: «На подписи» — факт, а не слово. Письмо, переданное на подпись, и не подписанное, несёт `awaiting_signature`
в карточке, `GET /documents` и `GET /registry`; до передачи и после подписи признака нет; статус остаётся `draft`."""

from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person, validate
from tests.signing import sign_out
from tests.test_letterhead_letters import deliver_letterhead
from tests.test_reply_path import reply_draft

pytestmark = pytest.mark.pg


async def seen(client: httpx.AsyncClient, who: Person, doc_id: str) -> dict[str, Any]:
    """Признак и статус в трёх представлениях: карточка, список документов, реестр."""
    card = (await client.get(f"/api/v1/documents/{doc_id}", headers=who.headers)).json()
    validate("Document", card)
    listed = await client.get("/api/v1/documents", params={"limit": 100}, headers=who.headers)
    [row] = [i for i in listed.json()["items"] if i["id"] == doc_id]
    registry = await client.get("/api/v1/registry", params={"limit": 100}, headers=who.headers)
    [entry] = [i for i in registry.json()["items"] if i["id"] == doc_id]
    validate("RegistryItem", entry)
    assert card["status"] == row["status"] == entry["status"]
    assert card["awaiting_signature"] == row["awaiting_signature"] == entry["awaiting_signature"]
    return {"status": card["status"], "awaiting": card["awaiting_signature"]}


async def test_letter_is_awaiting_signature_only_between_hand_over_and_signing(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await deliver_letterhead(client, container)
    manager = staff["manager"]
    doc = await reply_draft(client, manager, None)
    assert doc["awaiting_signature"] is False
    assert await seen(client, manager, doc["id"]) == {"status": "draft", "awaiting": False}

    handed = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=manager.headers)
    assert handed.status_code == 200, handed.text
    assert await seen(client, manager, doc["id"]) == {"status": "draft", "awaiting": True}

    signed = await sign_out(client, staff, doc["id"])
    assert signed.status_code == 200, signed.text
    assert await seen(client, manager, doc["id"]) == {"status": "sent", "awaiting": False}


async def test_other_kinds_are_never_awaiting_signature(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    created = await client.post(
        "/api/v1/documents",
        json={"kind": "memo", "subject": "Служебка", "text": "Текст", "addressee_crm_user_id": 3},
        headers=staff["manager"].headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["awaiting_signature"] is False
