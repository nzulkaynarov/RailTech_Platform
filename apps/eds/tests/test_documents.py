"""Документы (pg): создание и номера, отправка, маршрут служебной записки, возврат с новой версией, архив, видимость."""

from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person, outbox, validate
from tests.test_api_auth import assert_error

pytestmark = pytest.mark.pg

MEMO: dict[str, Any] = {"kind": "memo", "subject": "Закупка канцтоваров", "text": "Прошу согласовать закупку."}
WITH_AMOUNT = {**MEMO, "amount": {"amount": "1500000.00", "currency": "UZS"}, "due_date": "2026-11-05"}


async def create(client: httpx.AsyncClient, who: Person, **body: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/documents", json={**MEMO, **body}, headers=who.headers)
    assert response.status_code == 201, response.text
    doc: dict[str, Any] = response.json()
    validate("Document", doc)
    return doc


async def submit(client: httpx.AsyncClient, who: Person, doc_id: str, body: Any = None) -> httpx.Response:
    return await client.post(f"/api/v1/documents/{doc_id}/submit", json=body, headers=who.headers)


async def route_of(client: httpx.AsyncClient, who: Person, approval_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/v1/approvals/{approval_id}", headers=who.headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    validate("Approval", body)
    return body


async def decide(
    client: httpx.AsyncClient, who: Person, approval_id: str, decision: str, **extra: Any
) -> httpx.Response:
    return await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": decision, **extra}, headers=who.headers
    )


async def test_create_assigns_numbers_per_kind_and_publishes_registered(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    memo = await create(client, staff["manager"])
    assert (memo["number"], memo["status"], memo["version"]) == ("СЗ-2026/001", "draft", 1)
    assert memo["author"]["crm_user_id"] == 5
    assert memo["journal"][0]["action"] == "document.created"
    assert (await create(client, staff["manager"]))["number"] == "СЗ-2026/002"
    assert (await create(client, staff["manager"], kind="application"))["number"] == "ЗЯ-2026/001"
    assert (await create(client, staff["manager"], kind="report"))["number"] == "ОТ-2026/001"

    events = await outbox(container, "document.registered")
    assert [e["data"]["document"]["number"] for e in events] == [
        "СЗ-2026/001",
        "СЗ-2026/002",
        "ЗЯ-2026/001",
        "ОТ-2026/001",
    ]
    first = events[0]["data"]
    assert first["document"]["author"] == {"crm_user_id": 5, "full_name": "Алия Каримова"}
    assert first["actor"] == {"type": "staff", "crm_user_id": 5}
    assert await outbox(container, "approval.requested") == []  # маршрут открывает только submit


async def test_amount_due_and_deal_number_are_published(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = {
        "subject": "Запрос",
        "summary": "Суть",
        "sender": {"name": "ООО «Пример»"},
        "received_at": "2026-10-25",
        "links": {"erp_deal_id": 905, "deal_number": "ЗВ-2026-104"},
    }
    assert (await client.post("/api/v1/letters", json=letter, headers=staff["registrar"].headers)).status_code == 201
    doc = await create(client, staff["manager"], **WITH_AMOUNT, erp_deal_id=905, source_message_id="chat-msg-42")
    assert (doc["amount"], doc["due_date"], doc["deal_number"]) == (
        {"amount": "1500000.00", "currency": "UZS"},
        "2026-11-05",
        "ЗВ-2026-104",
    )
    [event] = await outbox(container, "document.registered")
    assert event["data"]["document"]["amount"] == {"amount": "1500000.00", "currency": "UZS"}
    assert event["data"]["document"]["deal_number"] == "ЗВ-2026-104"


async def test_create_validation(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    bad_amount = {"amount": "0.00", "currency": "UZS"}
    assert_error(
        await client.post("/api/v1/documents", json={**MEMO, "amount": bad_amount}, headers=staff["manager"].headers),
        422,
        "VALIDATION_FAILED",
    )
    for patch in (
        {"recipient": {"name": "ООО «Адресат»"}},  # адресат — только у исходящего письма
        {"in_reply_to": "00000000-0000-4000-8000-000000000000"},
        {"addressee_crm_user_id": 11},  # снабженец не согласует служебные записки
        {"addressee_crm_user_id": 999},
        {"kind": "contract"},
        {"subject": ""},
    ):
        response = await client.post("/api/v1/documents", json={**MEMO, **patch}, headers=staff["manager"].headers)
        assert_error(response, 422, "VALIDATION_FAILED")


async def test_permission_depends_on_document_kind(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    letter_out = {
        "kind": "letter_out",
        "subject": "Ответ",
        "text": "Здравствуйте",
        "recipient": {"name": "ООО «Пример»"},
    }
    # менеджер может служебки, но не исходящие письма
    denied = await client.post("/api/v1/documents", json=letter_out, headers=staff["manager"].headers)
    assert_error(denied, 403, "FORBIDDEN", permission="letters.register")
    # регистратор — наоборот: исходящие и служебки (у него memos.create), но
    assert (
        await client.post("/api/v1/documents", json=letter_out, headers=staff["registrar"].headers)
    ).status_code == 201
    # у «Администратора» только memos.create: исходящее письмо ему не положено
    assert_error(
        await client.post("/api/v1/documents", json=letter_out, headers=staff["admin"].headers), 403, "FORBIDDEN"
    )


async def test_memo_without_amount_goes_to_director_only_and_is_archived_on_approval(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    submitted = await submit(client, staff["manager"], doc["id"])
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()
    validate("Document", body)
    assert body["status"] == "on_approval"
    route = await route_of(client, staff["manager"], body["approval_id"])
    assert [(s["label"], s["assignee"], s["status"]) for s in route["steps"]] == [
        ("Директор", {"crm_user_id": None, "permission": "memos.approve"}, "current")
    ]
    assert route["template"] == "memo" and route["round"] == 1 and route["can_decide"] is False
    [requested] = await outbox(container, "approval.requested")
    assert requested["data"]["approval"]["object"] == {
        "kind": "memo",
        "eds_document_id": doc["id"],
        "number": "СЗ-2026/001",
    }
    assert requested["data"]["step"] == {"index": 1, "assignee": {"crm_user_id": None, "permission": "memos.approve"}}

    approved = await decide(client, staff["director"], body["approval_id"], "approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    after = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["manager"].headers)).json()
    validate("Document", after)
    assert (after["status"], after["archived_at"] is not None) == ("approved", True)
    assert after["decisions"][0]["decision"] == "approve" and after["decisions"][0]["by"]["crm_user_id"] == 3
    assert [e["action"] for e in after["journal"]] == [
        "document.created",
        "approval.requested",
        "document.submitted",
        "approval.decided",
        "document.archived",
    ]
    [decided] = await outbox(container, "approval.decided")
    assert (decided["data"]["decision"], decided["data"]["route_status"], decided["data"]["outgoing_number"]) == (
        "approve",
        "approved",
        None,
    )
    [archived] = await outbox(container, "document.archived")
    assert archived["data"]["document"]["number"] == "СЗ-2026/001"
    assert archived["data"]["reason"] == "approved"


async def test_memo_with_amount_goes_to_accountant_then_paid(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"], **WITH_AMOUNT)
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    route = await route_of(client, staff["manager"], approval_id)
    assert [s["label"] for s in route["steps"]] == ["Директор", "Бухгалтер"]
    assert route["steps"][1]["assignee"] == {"crm_user_id": None, "permission": "payments.confirm"}

    # бухгалтер на первом шаге не решает; очередь бухгалтера пуста
    assert_error(
        await decide(client, staff["accountant"], approval_id, "approve"), 403, "FORBIDDEN", reason="not_your_step"
    )
    queue = (await client.get("/api/v1/approvals", headers=staff["accountant"].headers)).json()
    assert queue["items"] == []

    step1 = await decide(client, staff["director"], approval_id, "approve")
    assert step1.status_code == 200
    assert step1.json()["status"] == "open" and step1.json()["steps"][1]["status"] == "current"
    mid = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["manager"].headers)).json()
    assert (mid["status"], mid["archived_at"]) == ("to_accountant", None)
    [decided1] = await outbox(container, "approval.decided")
    assert decided1["data"]["route_status"] == "open"
    assert await outbox(container, "document.archived") == []

    queue = (await client.get("/api/v1/approvals", headers=staff["accountant"].headers)).json()
    validate("ApprovalPage", queue)
    assert [i["id"] for i in queue["items"]] == [approval_id]
    assert queue["items"][0]["current_step"]["label"] == "Бухгалтер"
    detail = await route_of(client, staff["accountant"], approval_id)
    assert detail["can_decide"] is True and detail["allowed_decisions"] == ["approve", "return", "reject"]

    step2 = await decide(client, staff["accountant"], approval_id, "approve", comment="Оплачено платёжкой №15")
    assert step2.status_code == 200
    assert step2.json()["status"] == "approved"
    final = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["manager"].headers)).json()
    assert (final["status"], final["archived_at"] is not None) == ("paid", True)
    assert [d["decision"] for d in final["decisions"]] == ["approve", "approve"]
    [archived] = await outbox(container, "document.archived")
    assert archived["data"]["reason"] == "paid"


async def test_specific_addressee_decides_first_step(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    doc = await create(client, staff["manager"], addressee_crm_user_id=3)
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    route = await route_of(client, staff["manager"], approval_id)
    assert route["steps"][0]["assignee"] == {"crm_user_id": 3, "permission": None}
    assert doc["addressee"]["crm_user_id"] == 3
    assert (await decide(client, staff["director"], approval_id, "approve")).status_code == 200


async def test_return_needs_comment_and_resubmission_opens_new_version_and_round(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    first = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    for payload in ({}, {"comment": ""}, {"comment": "   "}):
        assert_error(await decide(client, staff["director"], first, "return", **payload), 422, "VALIDATION_FAILED")
        assert_error(await decide(client, staff["director"], first, "reject", **payload), 422, "VALIDATION_FAILED")

    returned = await decide(client, staff["director"], first, "return", comment="Добавьте смету")
    assert returned.status_code == 200
    assert returned.json()["status"] == "returned"
    mid = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["manager"].headers)).json()
    assert (mid["status"], mid["version"], mid["archived_at"]) == ("returned", 1, None)  # возврат — не конец маршрута
    assert await outbox(container, "document.archived") == []
    assert_error(await decide(client, staff["director"], first, "approve"), 409, "CONFLICT", reason="route_closed")

    resubmitted = await submit(
        client,
        staff["manager"],
        doc["id"],
        {"text": "Прошу согласовать. Смета приложена.", "amount": {"amount": "200000.00", "currency": "UZS"}},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    body = resubmitted.json()
    assert (body["status"], body["version"], body["text"]) == ("on_approval", 2, "Прошу согласовать. Смета приложена.")
    assert body["approval_id"] != first
    second = await route_of(client, staff["manager"], body["approval_id"])
    assert second["round"] == 2
    assert [s["label"] for s in second["steps"]] == ["Директор", "Бухгалтер"]  # сумма появилась — маршрут с бухгалтером
    assert [(d["round"], d["decision"], d["comment"]) for d in body["decisions"]] == [(1, "return", "Добавьте смету")]
    assert len(await outbox(container, "approval.requested")) == 2
    assert [e["data"]["decision"] for e in await outbox(container, "approval.decided")] == ["return"]


async def test_reject_is_final_and_archives_document(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"], kind="report")
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    rejected = await decide(client, staff["director"], approval_id, "reject", comment="Не по форме")
    assert rejected.status_code == 200
    final = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["manager"].headers)).json()
    assert (final["status"], final["archived_at"] is not None) == ("rejected", True)
    [archived] = await outbox(container, "document.archived")
    assert (archived["data"]["document"]["kind"], archived["data"]["reason"]) == ("report", "rejected")
    # отклонённый документ отправить снова нельзя
    assert_error(await submit(client, staff["manager"], doc["id"]), 409, "CONFLICT", reason="invalid_state")


async def test_application_and_report_need_only_director(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    for kind in ("application", "report"):
        doc = await create(client, staff["manager"], kind=kind, **{"amount": {"amount": "10.00", "currency": "UZS"}})
        approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
        route = await route_of(client, staff["manager"], approval_id)
        assert [s["label"] for s in route["steps"]] == ["Директор"] and route["template"] == kind


async def test_submit_rules(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    doc = await create(client, staff["manager"])
    # не автор: чужой черновик виден только автору (D1-10) → 404 и постороннему, и держателю registry.read
    assert_error(await submit(client, staff["admin"], doc["id"]), 404, "NOT_FOUND")
    assert_error(await submit(client, staff["accountant"], doc["id"]), 404, "NOT_FOUND")
    assert (await submit(client, staff["manager"], doc["id"])).status_code == 200
    assert_error(await submit(client, staff["manager"], doc["id"]), 409, "CONFLICT", reason="invalid_state")
    ghost = "00000000-0000-4000-8000-000000000000"
    assert_error(await submit(client, staff["manager"], ghost), 404, "NOT_FOUND")


async def test_outgoing_letter_is_numbered_on_send_and_archived(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = await client.post(
        "/api/v1/letters",
        json={"subject": "Запрос", "summary": "Суть", "sender": {"name": "ООО «Пример»"}, "received_at": "2026-10-25"},
        headers=staff["registrar"].headers,
    )
    draft = await create(
        client,
        staff["registrar"],
        kind="letter_out",
        recipient={"name": "ООО «Пример»", "inn": "123456789"},
        in_reply_to=letter.json()["id"],
    )
    assert draft["number"] is None and draft["status"] == "draft"
    assert (
        draft["recipient"] == {"name": "ООО «Пример»", "inn": "123456789"}
        and draft["in_reply_to"] == letter.json()["id"]
    )
    assert await outbox(container, "document.registered") == []  # номера ещё нет

    sent = await submit(client, staff["registrar"], draft["id"])
    assert sent.status_code == 200, sent.text
    body = sent.json()
    validate("Document", body)
    assert (body["number"], body["status"], body["approval_id"]) == ("ИСХ-001/26", "sent", None)
    assert body["archived_at"] is not None
    [registered] = await outbox(container, "document.registered")
    assert (
        registered["data"]["document"]["number"] == "ИСХ-001/26"
        and registered["data"]["document"]["kind"] == "letter_out"
    )
    [archived] = await outbox(container, "document.archived")
    assert archived["data"]["reason"] == "sent"
    assert await outbox(container, "approval.requested") == []
    assert_error(await submit(client, staff["registrar"], draft["id"]), 409, "CONFLICT", reason="invalid_state")
    second = await create(client, staff["registrar"], kind="letter_out", recipient={"name": "Другой"})
    assert (await submit(client, staff["registrar"], second["id"])).json()["number"] == "ИСХ-002/26"


async def test_document_visibility_author_participant_registry(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    mine = await create(client, staff["manager"], subject="Своя")
    other = await create(client, staff["supplier"], subject="Чужая")
    on_route = await create(client, staff["supplier"], subject="На маршруте")
    await submit(client, staff["supplier"], on_route["id"])

    def subjects(page: httpx.Response) -> list[str]:
        assert page.status_code == 200, page.text
        validate("DocumentPage", page.json())
        return [i["subject"] for i in page.json()["items"]]

    # менеджер с registry.read видит все, кроме чужих черновиков («Чужая», D1-10); «Администратор» — ничего чужого
    assert sorted(subjects(await client.get("/api/v1/documents", headers=staff["manager"].headers))) == [
        "На маршруте",
        "Своя",
    ]
    assert subjects(await client.get("/api/v1/documents", headers=staff["admin"].headers)) == []
    own = await create(client, staff["admin"], subject="Админская")
    assert subjects(await client.get("/api/v1/documents", headers=staff["admin"].headers)) == ["Админская"]
    assert_error(await client.get(f"/api/v1/documents/{other['id']}", headers=staff["admin"].headers), 404, "NOT_FOUND")
    assert (await client.get(f"/api/v1/documents/{own['id']}", headers=staff["admin"].headers)).status_code == 200
    # директор (держатель права шага) видит документ на своём маршруте; mine=1 — только свои
    assert subjects(await client.get("/api/v1/documents", params={"mine": 1}, headers=staff["manager"].headers)) == [
        "Своя"
    ]
    assert mine["status"] == "draft"
    kinds = await client.get(
        "/api/v1/documents", params=[("kind", "memo"), ("status", "on_approval")], headers=staff["director"].headers
    )
    assert subjects(kinds) == ["На маршруте"]


async def test_documents_cursor_pagination(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    for n in range(1, 4):
        await create(client, staff["manager"], subject=f"Док {n}")
    page1 = (await client.get("/api/v1/documents", params={"limit": 2}, headers=staff["manager"].headers)).json()
    assert [i["subject"] for i in page1["items"]] == ["Док 3", "Док 2"]
    page2 = (
        await client.get(
            "/api/v1/documents", params={"limit": 2, "cursor": page1["next_cursor"]}, headers=staff["manager"].headers
        )
    ).json()
    assert [i["subject"] for i in page2["items"]] == ["Док 1"] and page2["next_cursor"] is None


async def test_idempotent_document_creation(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    headers = {**staff["manager"].headers, "Idempotency-Key": "memo-key-0001"}
    one = await client.post("/api/v1/documents", json=MEMO, headers=headers)
    two = await client.post("/api/v1/documents", json=MEMO, headers=headers)
    assert (one.status_code, two.status_code, one.json() == two.json()) == (201, 201, True)
    assert len(await outbox(container, "document.registered")) == 1


async def patch(client: httpx.AsyncClient, who: Person, doc_id: str, body: Any) -> httpx.Response:
    return await client.patch(f"/api/v1/documents/{doc_id}", json=body, headers=who.headers)


async def test_author_edits_draft_without_sending(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    changed = await patch(
        client,
        staff["manager"],
        doc["id"],
        {
            "subject": "Новая тема",
            "amount": {"amount": "250000.00", "currency": "UZS"},
            "due_date": "2026-11-10",
            "erp_deal_id": 905,
        },
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    validate("Document", body)
    assert (body["subject"], body["text"], body["status"], body["version"], body["number"]) == (
        "Новая тема",
        MEMO["text"],  # не переданное поле не меняется
        "draft",
        1,
        "СЗ-2026/001",
    )
    assert (body["amount"], body["due_date"], body["erp_deal_id"]) == (
        {"amount": "250000.00", "currency": "UZS"},
        "2026-11-10",
        905,
    )
    assert body["journal"][-1]["action"] == "document.updated"
    assert await outbox(container, "approval.requested") == []  # маршрут не открывается

    cleared = await patch(client, staff["manager"], doc["id"], {"amount": None, "due_date": None, "erp_deal_id": None})
    assert cleared.status_code == 200
    assert (cleared.json()["amount"], cleared.json()["due_date"], cleared.json()["erp_deal_id"]) == (None, None, None)
    # правка не мешает отправке: маршрут без суммы — только директор
    sent = await submit(client, staff["manager"], doc["id"])
    assert sent.status_code == 200 and sent.json()["subject"] == "Новая тема"


async def test_update_rules(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    doc = await create(client, staff["manager"])
    # не автор: чужой черновик не виден никому (D1-10) → 404, в том числе держателю registry.read
    assert_error(await patch(client, staff["admin"], doc["id"], {"subject": "Чужая правка"}), 404, "NOT_FOUND")
    assert_error(await patch(client, staff["accountant"], doc["id"], {"subject": "Чужая правка"}), 404, "NOT_FOUND")
    assert_error(
        await patch(client, staff["manager"], doc["id"], {"amount": {"amount": "0.00", "currency": "UZS"}}),
        422,
        "VALIDATION_FAILED",
    )
    assert_error(await patch(client, staff["manager"], doc["id"], {"subject": ""}), 422, "VALIDATION_FAILED")
    assert_error(await patch(client, staff["manager"], doc["id"], {"kind": "report"}), 422, "VALIDATION_FAILED")
    ghost = "00000000-0000-4000-8000-000000000000"
    assert_error(await patch(client, staff["manager"], ghost, {"subject": "x"}), 404, "NOT_FOUND")
    assert_error(await patch(client, staff["nobody"], doc["id"], {"subject": "x"}), 403, "FORBIDDEN")


async def test_update_is_allowed_for_draft_and_returned_only(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    # на согласовании править нельзя
    assert_error(
        await patch(client, staff["manager"], doc["id"], {"subject": "Поздно"}),
        409,
        "CONFLICT",
        reason="invalid_state",
    )
    # после возврата автор правит и отправляет снова
    assert (await decide(client, staff["director"], approval_id, "return", comment="Уточните")).status_code == 200
    edited = await patch(client, staff["manager"], doc["id"], {"text": "Уточнено."})
    assert edited.status_code == 200 and edited.json()["status"] == "returned"
    resent = await submit(client, staff["manager"], doc["id"])
    assert (resent.json()["status"], resent.json()["version"], resent.json()["text"]) == ("on_approval", 2, "Уточнено.")
    # отправленное исходящее письмо править нельзя
    letter = await create(client, staff["registrar"], kind="letter_out", recipient={"name": "ООО «Пример»"})
    assert (await patch(client, staff["registrar"], letter["id"], {"subject": "Тема"})).status_code == 200
    assert (await submit(client, staff["registrar"], letter["id"])).status_code == 200
    assert_error(
        await patch(client, staff["registrar"], letter["id"], {"subject": "Поздно"}),
        409,
        "CONFLICT",
        reason="invalid_state",
    )
    # чужой черновик письма менеджеру не виден (D1-10): 404, а не 403
    other = await create(client, staff["registrar"], kind="letter_out", recipient={"name": "Другой"})
    assert_error(await patch(client, staff["manager"], other["id"], {"subject": "x"}), 404, "NOT_FOUND")


async def test_update_changes_recipient_only_for_outgoing_letter(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    letter = await create(client, staff["registrar"], kind="letter_out", recipient={"name": "ООО «Пример»"})
    changed = await patch(
        client, staff["registrar"], letter["id"], {"recipient": {"name": "АО «Другое»", "inn": "123456789"}}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["recipient"] == {"name": "АО «Другое»", "inn": "123456789"}
    memo = await create(client, staff["registrar"])
    assert_error(
        await patch(client, staff["registrar"], memo["id"], {"recipient": {"name": "Адресат"}}),
        422,
        "VALIDATION_FAILED",
    )


async def test_update_and_submit_reject_explicit_null_for_subject_and_text(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    for field in ("subject", "text"):
        assert_error(await patch(client, staff["manager"], doc["id"], {field: None}), 422, "VALIDATION_FAILED")
        assert_error(await submit(client, staff["manager"], doc["id"], {field: None}), 422, "VALIDATION_FAILED")
    still = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["manager"].headers)).json()
    assert (still["subject"], still["status"]) == (MEMO["subject"], "draft")
