"""Правки по ревью лида (E3, pg): разделение обязанностей, версии КП, шаги маршрута, файлы, гонка регистрации."""

from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from app.security.access_token import issue_access_token
from app.services import letters as letters_service
from tests.conftest import ACCESS_SECRET
from tests.domain import Person, deliver_erp, erp_event, outbox
from tests.helpers import bearer, seed_employee
from tests.test_api_auth import assert_error
from tests.test_documents import WITH_AMOUNT, create, decide, route_of, submit
from tests.test_files import PDF, upload
from tests.test_letters import NEW_LETTER, register
from tests.test_quotes import only_route

pytestmark = pytest.mark.pg


def headers_of(user_id: int) -> dict[str, str]:
    return bearer(issue_access_token(user_id, ACCESS_SECRET))


# --- 1. разделение обязанностей ------------------------------------------------------------------------------------


async def test_sole_approver_may_decide_own_document(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    doc = await create(client, staff["director"], subject="Служебка директора")
    approval_id = (await submit(client, staff["director"], doc["id"])).json()["approval_id"]
    assert (await route_of(client, staff["director"], approval_id))["can_decide"] is True
    assert (await decide(client, staff["director"], approval_id, "approve")).status_code == 200


async def test_author_cannot_decide_own_document_while_another_holder_exists(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await seed_employee(container, 20, full_name="Заместитель Директора", permissions={"eds": ["memos.approve"]})
    doc = await create(client, staff["director"], subject="Служебка директора")
    approval_id = (await submit(client, staff["director"], doc["id"])).json()["approval_id"]

    assert_error(
        await decide(client, staff["director"], approval_id, "approve"), 403, "FORBIDDEN", reason="not_your_step"
    )
    own = await route_of(client, staff["director"], approval_id)
    assert own["can_decide"] is False and own["allowed_decisions"] == []
    assert (await client.get("/api/v1/approvals", headers=staff["director"].headers)).json()["items"] == []

    deputy = headers_of(20)
    assert [i["id"] for i in (await client.get("/api/v1/approvals", headers=deputy)).json()["items"]] == [approval_id]
    approved = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=deputy
    )
    assert approved.status_code == 200


async def test_accountant_author_cannot_confirm_own_payment_when_another_accountant_exists(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await seed_employee(container, 21, permissions={"eds": ["payments.confirm"]})
    doc = await create(client, staff["accountant"], **WITH_AMOUNT)
    approval_id = (await submit(client, staff["accountant"], doc["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], approval_id, "approve")).status_code == 200
    # шаг «бухгалтер»: автор — бухгалтер, есть второй держатель payments.confirm
    assert_error(
        await decide(client, staff["accountant"], approval_id, "approve"), 403, "FORBIDDEN", reason="not_your_step"
    )
    other = await client.post(
        f"/api/v1/documents/{doc['id']}/payment",
        json={"paid_on": "2026-10-20", "amount": {"amount": "1500000.00", "currency": "UZS"}},
        headers=headers_of(21),
    )
    assert other.status_code == 200, other.text


async def test_addressee_cannot_be_the_author(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    body = {"kind": "memo", "subject": "Себе", "text": "Текст", "addressee_crm_user_id": 3}
    assert_error(
        await client.post("/api/v1/documents", json=body, headers=staff["director"].headers), 422, "VALIDATION_FAILED"
    )
    assert (await client.post("/api/v1/documents", json=body, headers=staff["manager"].headers)).status_code == 201


async def test_quote_route_has_no_author_restriction(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await seed_employee(container, 22, permissions={"eds": ["approvals.decide"]})
    await deliver_erp(client, container, erp_event("erp/quote.ready_for_approval.v1"))
    route = await only_route(client, staff["director"])
    assert route["can_decide"] is True


# --- 2. новая версия КП закрывает прежнюю ----------------------------------------------------------------------------


async def test_new_quote_version_supersedes_open_route_of_old_one(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, erp_event("erp/quote.ready_for_approval.v1", version=1))
    first = await only_route(client, staff["director"])
    await deliver_erp(client, container, erp_event("erp/quote.ready_for_approval.v1", version=2))

    old = await route_of(client, staff["director"], first["id"])
    assert (old["status"], old["closed_at"] is not None, old["can_decide"]) == ("returned", True, False)
    assert [s["status"] for s in old["steps"]] == ["skipped"]
    assert await outbox(container, "approval.decided") == []  # решения директора не было
    assert_error(
        await decide(client, staff["director"], first["id"], "approve"), 409, "CONFLICT", reason="route_closed"
    )

    queue = (await client.get("/api/v1/approvals", headers=staff["director"].headers)).json()["items"]
    assert [i["object"]["quote_version"] for i in queue] == [2]
    async with container.session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT action, comment, by_crm_user_id FROM journal WHERE action = 'approval.superseded'")
            )
        ).all()
    assert [(a, c, b) for a, c, b in rows] == [("approval.superseded", "заменён версией 2", None)]

    approved = await decide(client, staff["director"], queue[0]["id"], "approve")
    assert approved.status_code == 200 and approved.json()["outgoing_number"] == "ИСХ-001/26"
    numbers = [e["data"]["outgoing_number"] for e in await outbox(container, "approval.decided")]
    assert numbers == ["ИСХ-001/26"]  # по КП ушёл ровно один исходящий номер


# --- 3. файлы: версии только пока объект редактируется -------------------------------------------------------------


async def test_file_version_is_refused_after_document_goes_to_approval(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    ref = (await upload(client, staff["manager"])).json()
    doc = await create(client, staff["manager"], file_ids=[ref["id"]])
    assert (await upload(client, staff["manager"], PDF + b"2", version_of=ref["id"])).status_code == 201  # draft
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    frozen = await upload(client, staff["manager"], PDF + b"3", version_of=ref["id"])
    assert_error(frozen, 409, "CONFLICT", reason="invalid_state")
    await decide(client, staff["director"], approval_id, "return", comment="Поправьте")
    assert (await upload(client, staff["manager"], PDF + b"4", version_of=ref["id"])).status_code == 201  # returned


async def test_file_version_of_a_resolved_letter_is_refused(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    ref = (await upload(client, staff["registrar"])).json()
    letter = await client.post(
        "/api/v1/letters", json={**NEW_LETTER, "file_ids": [ref["id"]]}, headers=staff["registrar"].headers
    )
    assert (await upload(client, staff["registrar"], PDF + b"2", version_of=ref["id"])).status_code == 201
    await client.post(
        f"/api/v1/letters/{letter.json()['id']}/reject", json={"reason": "Нет"}, headers=staff["director"].headers
    )
    assert_error(
        await upload(client, staff["registrar"], PDF + b"3", version_of=ref["id"]),
        409,
        "CONFLICT",
        reason="invalid_state",
    )


async def test_oversized_upload_is_refused_by_content_length_before_parsing(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    from app.services.storage import TEST_STORAGE

    headers = {**staff["manager"].headers, "Content-Length": str(30 * 1024 * 1024)}
    response = await client.post("/api/v1/files", files={"file": ("a.pdf", PDF, "application/pdf")}, headers=headers)
    assert_error(response, 413, "PAYLOAD_TOO_LARGE")
    assert TEST_STORAGE.objects == {}


# --- 4. адресат письма фиксируется при регистрации -------------------------------------------------------------------


async def test_default_addressee_is_stored_at_registration(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = await register(client, staff["registrar"])
    assert letter["addressee"]["crm_user_id"] == 3
    # позже появился другой держатель letters.resolve с меньшим id — адресат уже зафиксирован
    await seed_employee(container, 2, full_name="Новый Директор", permissions={"eds": ["letters.resolve"]})
    again = (await client.get(f"/api/v1/letters/{letter['id']}", headers=staff["manager"].headers)).json()
    assert again["addressee"]["crm_user_id"] == 3
    fresh = await register(client, staff["registrar"], links={})
    assert fresh["addressee"]["crm_user_id"] == 2


async def test_letter_without_any_director_keeps_the_fallback(client: httpx.AsyncClient, container: Container) -> None:
    await seed_employee(container, 4, full_name="Регина", permissions={"eds": ["letters.register", "letters.read"]})
    response = await client.post("/api/v1/letters", json=NEW_LETTER, headers=headers_of(4))
    assert response.status_code == 201
    assert response.json()["addressee"]["crm_user_id"] == 0


# --- 6. гонка ручной регистрации с request.created -------------------------------------------------------------------


async def test_manual_registration_losing_the_race_for_a_request_gets_409(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], monkeypatch: pytest.MonkeyPatch
) -> None:
    await deliver_erp(client, container, erp_event("erp/request.created.v1"))  # заявка 77 уже занята письмом
    before = len(await outbox(container, "letter.registered"))

    async def pre_check_missed(session: Any, erp_request_id: int) -> None:
        return None  # проверка «заявка свободна» прошла до того, как обработчик записал своё письмо

    monkeypatch.setattr(letters_service, "find_by_request", pre_check_missed)
    response = await client.post("/api/v1/letters", json=NEW_LETTER, headers=staff["registrar"].headers)
    assert_error(response, 409, "CONFLICT", reason="letter_exists_for_request")
    monkeypatch.undo()
    assert len(await outbox(container, "letter.registered")) == before
    # номер не сгорел: следующая регистрация получает ВХ-002
    assert (await register(client, staff["registrar"], links={}))["number"] == "ВХ-002/26"


# --- 7. approval.requested на каждом шаге ----------------------------------------------------------------------------


async def test_next_step_publishes_approval_requested_with_its_index(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"], **WITH_AMOUNT)
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    [first] = await outbox(container, "approval.requested")
    assert first["data"]["step"]["index"] == 1

    await decide(client, staff["director"], approval_id, "approve")
    requested = await outbox(container, "approval.requested")
    assert [e["data"]["step"] for e in requested] == [
        {"index": 1, "assignee": {"crm_user_id": None, "permission": "memos.approve"}},
        {"index": 2, "assignee": {"crm_user_id": None, "permission": "payments.confirm"}},
    ]
    assert requested[1]["data"]["approval"]["eds_approval_id"] == approval_id
    assert requested[1]["data"]["actor"] == {"type": "staff", "crm_user_id": 3}
    decided_before = [e["type"] for e in await outbox(container)]
    assert decided_before.index("uz.railtech.eds.approval.decided.v1") < decided_before.index(
        "uz.railtech.eds.approval.requested.v1", decided_before.index("uz.railtech.eds.approval.decided.v1")
    )
    # конец маршрута или возврат нового шага не открывают
    await client.post(
        f"/api/v1/documents/{doc['id']}/payment",
        json={"paid_on": "2026-10-20", "amount": {"amount": "1500000.00", "currency": "UZS"}},
        headers=staff["accountant"].headers,
    )
    assert len(await outbox(container, "approval.requested")) == 2
