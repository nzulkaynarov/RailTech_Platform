"""СЦ-9 (решение владельца 2026-11-21 (3)): исходящее письмо получает номер и уходит только через «Подписать»;
`POST /documents/{id}/submit` для `letter_out` — 409 `signature_required` на любом пути (автор, делопроизводитель,
переданный черновик, `send = true`); строки «Зарегистрировать» в «Моих задачах» нет."""

import httpx
import pytest

from app.container import Container
from tests.domain import Person, outbox
from tests.signing import sign_out
from tests.test_api_auth import assert_error
from tests.test_letterhead_letters import deliver_letterhead
from tests.test_reply_path import reply_draft, tasks_of

pytestmark = pytest.mark.pg


async def counter(container: Container) -> int:
    from sqlalchemy import text

    async with container.session_factory() as session:
        row = (await session.execute(text("SELECT coalesce(max(last_value), 0) FROM number_counters"))).scalar_one()
    return int(row)


@pytest.mark.parametrize("who", ["manager", "registrar"])
@pytest.mark.parametrize("body", [None, {"send": True}])
async def test_submit_never_registers_an_outgoing_letter(
    client: httpx.AsyncClient,
    staff: dict[str, Person],
    container: Container,
    who: str,
    body: dict[str, bool] | None,
) -> None:
    await deliver_letterhead(client, container)
    doc = await reply_draft(client, staff["manager"], None)
    handed = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    assert handed.status_code == 200, handed.text
    before = await counter(container)

    refused = await client.post(f"/api/v1/documents/{doc['id']}/submit", json=body, headers=staff[who].headers)
    if who == "manager":  # у автора без `letters.register` отказ по праву, как и раньше
        assert_error(refused, 403, "FORBIDDEN", permission="letters.register")
    else:
        assert_error(refused, 409, "CONFLICT", reason="signature_required")
        assert refused.json()["details"]["status"] == "draft"

    card = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["registrar"].headers)).json()
    assert (card["status"], card["number"]) == ("draft", None)
    assert await counter(container) == before
    assert await outbox(container, "document.registered") == []
    assert await outbox(container, "document.archived") == []


async def test_unsigned_letter_cannot_be_sent_again(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await deliver_letterhead(client, container)
    doc = await reply_draft(client, staff["registrar"], None)
    refused = await client.post(f"/api/v1/documents/{doc['id']}/send", headers=staff["registrar"].headers)
    assert_error(refused, 409, "CONFLICT", reason="invalid_state")


async def test_handed_over_draft_is_a_signature_task_only(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    doc = await reply_draft(client, staff["manager"], None)
    await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    for name in ("registrar", "director", "manager"):
        assert (await tasks_of(client, staff[name]))["registrations"] == [], name


async def test_signing_is_the_only_way_to_a_number(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await deliver_letterhead(client, container)
    doc = await reply_draft(client, staff["registrar"], None)
    signed = await sign_out(client, staff, doc["id"])
    assert signed.status_code == 200, signed.text
    body = signed.json()
    assert body["status"] == "sent" and body["number"].startswith("OUT-") and body["signed_at"] is not None
    assert len(await outbox(container, "document.registered")) == 1
