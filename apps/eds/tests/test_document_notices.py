"""Уведомления по документам без входящего письма (СЦ-9, pg): автор служебки узнаёт о решении и оплате, подписант — о
переданном письме, автор письма — о подписи другого; «подписать некому» уходит держателям `signing.manage`."""

import json
import uuid
from typing import Any

import httpx
import jsonschema
import pytest
from referencing import Registry, Resource
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.models import Employee
from app.services import documents
from tests.domain import Person, outbox
from tests.helpers import EVENTS
from tests.test_documents import WITH_AMOUNT, create, decide, submit
from tests.test_letterhead_letters import deliver_letterhead, letter_json
from tests.test_outbox_atomicity import rolled_back
from tests.test_payments import MONEY, pay, to_accountant
from tests.test_reply_path import incoming_for, reply_draft

pytestmark = pytest.mark.pg

CHARTER: dict[str, Any] = {"crm_user_id": 3, "kinds": ["letter_out"], "basis": "charter", "valid_from": "2026-01-01"}


def _registry() -> Any:
    registry = Registry()
    for name in ("_defs.v1.json", "_defs.v2.json"):
        defs = json.loads((EVENTS / "eds" / name).read_text(encoding="utf-8"))
        registry = registry.with_resource(defs["$id"], Resource.from_contents(defs))
    return registry


LEGACY_KINDS = {"memo_decided", "memo_paid", "letter_sign_requested", "letter_signer_missing", "letter_signed"}


async def notices(container: Container, kind: str | None = None) -> list[dict[str, Any]]:
    found = [e["data"] for e in await outbox(container, "document.notice_requested")]
    for data in found:  # каждое событие соответствует схеме каталога
        schema = json.loads((EVENTS / "eds" / "document.notice_requested.v2.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(
            schema, registry=_registry(), format_checker=jsonschema.FormatChecker()
        ).validate(data)
    if kind is None:  # СЦ-9: без вида — только прежние виды; сигналы о задачах (ГЛ-2) — в test_task_notices.py
        return [d for d in found if d["kind"] in LEGACY_KINDS]
    return [d for d in found if d["kind"] == kind]


async def authorise(client: httpx.AsyncClient, staff: dict[str, Person], **body: Any) -> None:
    response = await client.post(
        "/api/v1/signing/authorities", json={**CHARTER, **body}, headers=staff["admin"].headers
    )
    assert response.status_code == 201, response.text


async def hand_over(client: httpx.AsyncClient, who: Person, **changes: Any) -> dict[str, Any]:
    created = await client.post("/api/v1/documents", json=letter_json(**changes), headers=who.headers)
    assert created.status_code == 201, created.text
    doc: dict[str, Any] = created.json()
    handed = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=who.headers)
    assert handed.status_code == 200, handed.text
    return doc


async def test_author_learns_that_the_director_approved_the_memo(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    assert await notices(container) == []  # пока решения нет — тишина
    assert (await decide(client, staff["director"], approval_id, "approve")).status_code == 200

    [notice] = await notices(container, "memo_decided")
    assert notice["recipients"] == [5]  # автор; директор, принявший решение, — нет
    assert notice["title"] == f"Служебка {doc['number']} согласована"
    assert notice["document"] == {"eds_document_id": doc["id"], "number": doc["number"], "subject": doc["subject"]}
    assert notice["actor"] == {"type": "staff", "crm_user_id": 3}


async def test_author_learns_about_the_rejection_with_the_comment(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], approval_id, "reject", comment="Нет бюджета")).status_code == 200

    [notice] = await notices(container, "memo_decided")
    assert (notice["recipients"], notice["title"], notice["subtitle"]) == (
        [5],
        f"Служебка {doc['number']} отклонена",
        "Нет бюджета",
    )


async def test_return_for_rework_is_not_duplicated_and_own_decision_is_not_announced(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], approval_id, "return", comment="Уточните")).status_code == 200
    assert await notices(container) == []  # возврат — строка «Доработать», не колокольчик
    # директор написал и сам согласовал: себе не пишем
    own = await create(client, staff["director"])
    own_route = (await submit(client, staff["director"], own["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], own_route, "approve")).status_code == 200
    assert await notices(container) == []


async def test_memo_with_amount_goes_to_the_accountant_then_payment_is_announced_once(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc_id, _ = await to_accountant(client, staff, **WITH_AMOUNT)
    [decided] = await notices(container, "memo_decided")
    assert decided["recipients"] == [5] and "Передана на оплату" in decided["subtitle"]

    paid = await pay(client, staff["accountant"], doc_id)
    assert paid.status_code == 200, paid.text
    assert await pay(client, staff["accountant"], doc_id) is not None  # повтор тех же данных
    [announced] = await notices(container, "memo_paid")
    assert announced["recipients"] == [5] and announced["title"].endswith("оплачена")
    assert announced["subtitle"].endswith(f"{MONEY['amount']} UZS")
    assert len(await notices(container, "memo_decided")) == 1  # оплата не повторяет «согласована»


async def test_handed_over_letter_goes_only_to_the_computed_signer(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await authorise(client, staff)
    doc = await hand_over(client, staff["manager"])

    [notice] = await notices(container)
    assert (notice["kind"], notice["recipients"]) == (
        "letter_sign_requested",
        [3],
    )  # директор, не все делопроизводители
    assert notice["document"]["number"] is None and notice["document"]["eds_document_id"] == doc["id"]
    assert doc["subject"] in notice["subtitle"] and "Алия Каримова" in notice["subtitle"]
    again = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    assert again.status_code == 200 and len(await notices(container)) == 1  # повтор передачи — без второго события


async def test_nobody_can_sign_tells_the_holders_of_signing_manage(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await hand_over(client, staff["manager"])  # реестр полномочий пуст

    [notice] = await notices(container)
    assert notice["kind"] == "letter_signer_missing" and notice["title"] == "Подписать некому"
    assert 9 in notice["recipients"] and 5 not in notice["recipients"] and 4 not in notice["recipients"]
    assert "Права подписи" in notice["subtitle"]


async def test_the_only_signer_being_the_author_without_letters_register_gets_no_missing_notice(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await authorise(client, staff, crm_user_id=5)  # автор с полномочием, без letters.register: подписывает сам (СОТР-1)
    await hand_over(client, staff["manager"])
    assert await notices(container) == []  # «Подписать некому» нет, а подписанту-автору писать не о чем


async def test_holder_without_letters_register_is_asked_to_sign(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await authorise(client, staff, crm_user_id=6)  # бухгалтер: полномочие есть, раздела регистрации нет (СОТР-1)
    await hand_over(client, staff["manager"])
    [notice] = await notices(container)
    assert notice["kind"] == "letter_sign_requested" and notice["recipients"] == [6]


async def test_reply_letter_signer_gets_sign_notice_even_if_holds_letters_register(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_letterhead(client, container)
    await authorise(client, staff)
    incoming = await incoming_for(client, staff)
    doc = await reply_draft(client, staff["manager"], incoming["id"])
    handed = await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    assert handed.status_code == 200, handed.text
    [notice] = await notices(container)  # директор держит letters.register, но просят его подписать, не регистрировать
    assert (notice["kind"], notice["title"]) == ("letter_sign_requested", "Подпишите исходящее")
    assert notice["recipients"] == [staff["director"].id]


async def test_author_learns_that_someone_else_signed_the_letter(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], deferred: list[str]
) -> None:
    await deliver_letterhead(client, container)
    await authorise(client, staff)
    doc = await hand_over(client, staff["manager"])
    signed = await client.post(
        f"/api/v1/documents/{doc['id']}/sign", json={"send": False}, headers=staff["director"].headers
    )
    assert signed.status_code == 200, signed.text

    [notice] = await notices(container, "letter_signed")
    number = signed.json()["number"]
    assert notice["recipients"] == [5] and notice["title"] == f"Письмо {number} подписано"
    assert "Рустам Директоров" in notice["subtitle"] and notice["document"]["number"] == number


async def test_handover_notice_rolled_back_leaves_no_event(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await authorise(client, staff)
    created = await client.post("/api/v1/documents", json=letter_json(), headers=staff["manager"].headers)
    doc_id = uuid.UUID(created.json()["id"])

    async def op(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await documents.request_registration(session, bus, employee=who, document_id=doc_id)
        queued = await session.execute(text("SELECT count(*) FROM rt_bus_outbox WHERE type LIKE '%document.notice%'"))
        assert queued.scalar_one() == 1  # внутри транзакции событие есть

    await rolled_back(container, 5, op)  # после отката — ни события, ни журнала
    assert await notices(container) == []


async def test_author_with_authority_hands_the_draft_to_another_signer(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await authorise(client, staff, crm_user_id=5)  # автор вправе подписывать, но не свои письма (ADR-0024 п. 3)
    await authorise(client, staff)
    await hand_over(client, staff["manager"])
    [notice] = await notices(container)
    assert (notice["kind"], notice["recipients"]) == ("letter_sign_requested", [3])


async def test_signed_reply_is_announced_by_the_sign_request_only(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], deferred: list[str]
) -> None:
    await deliver_letterhead(client, container)
    await authorise(client, staff)
    incoming = await incoming_for(client, staff)
    doc = await reply_draft(client, staff["manager"], incoming["id"])
    await client.post(f"/api/v1/documents/{doc['id']}/registration-request", headers=staff["manager"].headers)
    signed = await client.post(
        f"/api/v1/documents/{doc['id']}/sign", json={"send": False}, headers=staff["director"].headers
    )
    assert signed.status_code == 200, signed.text
    assert [n["kind"] for n in await notices(container)] == ["letter_sign_requested"]  # «Зарегистрируйте» больше нет
