"""«Оплачено» для служебной записки с суммой (D2-4, pg): оплата, права, объекты, идемпотентность, правила суммы."""

from datetime import timedelta
from typing import Any

import httpx
import pytest

from app import clock
from app.container import Container
from tests.domain import Person, outbox, validate
from tests.helpers import seed_employee
from tests.test_api_auth import assert_error
from tests.test_documents import WITH_AMOUNT, create, decide, submit
from tests.test_files import PDF, upload
from tests.test_review_rules import headers_of

pytestmark = pytest.mark.pg

MONEY = {"amount": "1500000.00", "currency": "UZS"}


def today() -> str:
    return clock.company_date(clock.now()).isoformat()


async def pay(client: httpx.AsyncClient, headers: dict[str, str] | Person, doc_id: str, **body: Any) -> httpx.Response:
    payload = {"paid_on": today(), "amount": MONEY, **body}
    return await client.post(
        f"/api/v1/documents/{doc_id}/payment",
        json=payload,
        headers=headers.headers if isinstance(headers, Person) else headers,
    )


async def to_accountant(client: httpx.AsyncClient, staff: dict[str, Person], **fields: Any) -> tuple[str, str]:
    """Записка с суммой согласована директором и передана бухгалтеру: `(id документа, id маршрута)`."""
    doc = await create(client, staff["manager"], **{**WITH_AMOUNT, **fields})
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], approval_id, "approve")).status_code == 200
    return doc["id"], approval_id


async def test_accountant_pays_with_receipt_and_the_journal_records_it(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc_id, approval_id = await to_accountant(client, staff)
    receipt = (await upload(client, staff["accountant"], name="платёжка.pdf")).json()
    paid_day = (clock.company_date(clock.now()) - timedelta(days=1)).isoformat()

    response = await pay(
        client, staff["accountant"], doc_id, paid_on=paid_day, receipt_file_id=receipt["id"], note="Платёжка №15"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    validate("Document", body)
    assert body["status"] == "paid" and body["archived_at"] is not None
    assert body["payment"]["paid_on"] == paid_day and body["payment"]["amount"] == MONEY
    assert body["payment"]["receipt_file_id"] == receipt["id"] and body["payment"]["paid_by"]["crm_user_id"] == 6
    assert receipt["id"] in [f["id"] for f in body["files"]]
    paid_entry = next(e for e in body["journal"] if e["action"] == "document.paid")
    assert paid_entry["by"]["crm_user_id"] == 6 and paid_entry["file_id"] == receipt["id"]
    assert paid_entry["comment"].endswith("1500000.00 UZS")
    [decided_last] = (await outbox(container, "approval.decided"))[1:]
    assert decided_last["data"]["route_status"] == "approved" and decided_last["data"]["decision"] == "approve"
    [archived] = await outbox(container, "document.archived")
    assert archived["data"]["reason"] == "paid"
    route = (await client.get(f"/api/v1/approvals/{approval_id}", headers=staff["accountant"].headers)).json()
    assert route["status"] == "approved" and route["can_decide"] is False


async def test_pay_without_receipt_and_a_lesser_amount_is_allowed(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc_id, _ = await to_accountant(client, staff)
    response = await pay(client, staff["accountant"], doc_id, amount={"amount": "1499999.50", "currency": "UZS"})
    assert response.status_code == 200, response.text
    assert response.json()["payment"]["receipt_file_id"] is None
    assert response.json()["payment"]["amount"]["amount"] == "1499999.50"


async def test_repeat_with_the_same_data_is_idempotent_other_data_is_a_conflict(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc_id, _ = await to_accountant(client, staff)
    first = await pay(client, staff["accountant"], doc_id)
    second = await pay(client, staff["accountant"], doc_id)
    assert first.status_code == second.status_code == 200
    assert first.json()["payment"] == second.json()["payment"]
    assert len(await outbox(container, "document.archived")) == 1
    assert [e["action"] for e in second.json()["journal"]].count("document.paid") == 1
    other = await pay(client, staff["accountant"], doc_id, amount={"amount": "1000.00", "currency": "UZS"})
    assert_error(other, 409, "CONFLICT", reason="already_paid")


async def test_repeat_with_the_same_date_and_amount_but_another_receipt_is_a_conflict(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc_id, _ = await to_accountant(client, staff)
    first_receipt = (await upload(client, staff["accountant"], name="a.pdf")).json()
    other_receipt = (await upload(client, staff["accountant"], name="b.pdf")).json()
    assert (await pay(client, staff["accountant"], doc_id, receipt_file_id=first_receipt["id"])).status_code == 200
    again = await pay(client, staff["accountant"], doc_id, receipt_file_id=first_receipt["id"])
    assert again.status_code == 200
    changed = await pay(client, staff["accountant"], doc_id, receipt_file_id=other_receipt["id"])
    assert_error(changed, 409, "CONFLICT", reason="already_paid")
    without = await pay(client, staff["accountant"], doc_id)
    assert_error(without, 409, "CONFLICT", reason="already_paid")


@pytest.mark.parametrize("who", ["manager", "supplier", "engineer", "registrar", "admin", "nobody"])
async def test_roles_without_the_payment_right_get_403_directly(
    client: httpx.AsyncClient, staff: dict[str, Person], who: str
) -> None:
    doc_id, _ = await to_accountant(client, staff)
    response = await pay(client, staff[who], doc_id)
    assert_error(response, 403, "FORBIDDEN")
    detail = (await client.get(f"/api/v1/documents/{doc_id}", headers=staff["accountant"].headers)).json()
    assert detail["status"] == "to_accountant" and detail["payment"] is None


async def test_a_reader_with_only_registry_read_cannot_pay(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await seed_employee(container, 30, permissions={"eds": ["registry.read", "memos.create"]})
    doc_id, _ = await to_accountant(client, staff)
    assert_error(await pay(client, headers_of(30), doc_id), 403, "FORBIDDEN", permission="payments.confirm")
    assert (await client.get(f"/api/v1/documents/{doc_id}", headers=headers_of(30))).status_code == 200


async def test_a_director_with_the_catalog_codes_reads_the_memo_but_cannot_pay(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Q-D2-4-1 п. 1: «Счета и оплаты» у директора — read: все коды, кроме `payments.confirm`."""
    director_codes = [
        "letters.read",
        "letters.register",
        "letters.resolve",
        "memos.create",
        "memos.approve",
        "approvals.decide",
        "registry.read",
        "registry.export",
    ]
    await seed_employee(container, 32, permissions={"eds": director_codes})
    doc_id, _ = await to_accountant(client, staff)
    assert_error(await pay(client, headers_of(32), doc_id), 403, "FORBIDDEN", permission="payments.confirm")
    assert (await client.get(f"/api/v1/documents/{doc_id}", headers=headers_of(32))).status_code == 200
    detail = (await client.get(f"/api/v1/documents/{doc_id}", headers=staff["accountant"].headers)).json()
    assert detail["status"] == "to_accountant" and detail["payment"] is None


async def test_pay_before_the_director_approves_or_for_a_memo_without_amount_is_a_conflict(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"], **WITH_AMOUNT)
    await submit(client, staff["manager"], doc["id"])
    assert_error(await pay(client, staff["accountant"], doc["id"]), 409, "CONFLICT", reason="invalid_state")
    # свои черновики: чужой черновик бухгалтеру не виден (D1-10) — отказ был бы 404, а не состояние
    me = staff["accountant"]
    draft = await create(client, me, **WITH_AMOUNT)
    assert_error(await pay(client, me, draft["id"]), 409, "CONFLICT", reason="invalid_state")
    no_amount = await create(client, me)
    assert_error(await pay(client, me, no_amount["id"]), 409, "CONFLICT", reason="invalid_state")
    report = await create(client, me, kind="report", amount=MONEY)
    assert_error(await pay(client, me, report["id"]), 409, "CONFLICT", reason="invalid_state")


async def test_unknown_document_is_404(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    assert_error(await pay(client, staff["accountant"], "00000000-0000-4000-8000-000000000000"), 404, "NOT_FOUND")


async def test_the_accountant_of_another_memo_without_visibility_gets_404(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Держатель только `payments.confirm` (без `registry.read`) не видит записку без суммы: существование скрыто."""
    await seed_employee(container, 31, permissions={"eds": ["payments.confirm"]})
    doc = await create(client, staff["manager"])
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], approval_id, "approve")).status_code == 200
    assert_error(await pay(client, headers_of(31), doc["id"]), 404, "NOT_FOUND")


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        ({"amount": {"amount": "1500000.01", "currency": "UZS"}}, "amount", "exceeds_approved"),
        ({"amount": {"amount": "1500000.00", "currency": "USD"}}, "amount", "currency_mismatch"),
        ({"amount": {"amount": "0.00", "currency": "UZS"}}, "amount", "must_be_positive"),
        ({"paid_on": "2999-01-01"}, "paid_on", "in_future"),
    ],
)
async def test_amount_currency_and_date_rules(
    client: httpx.AsyncClient, staff: dict[str, Person], body: dict[str, Any], field: str, message: str
) -> None:
    doc_id, _ = await to_accountant(client, staff)
    response = await pay(client, staff["accountant"], doc_id, **body)
    assert_error(response, 422, "VALIDATION_FAILED")
    assert response.json()["details"]["fields"][0] == {"field": field, "message": message, "type": "value_error"}
    after = (await client.get(f"/api/v1/documents/{doc_id}", headers=staff["accountant"].headers)).json()
    assert after["status"] == "to_accountant" and after["payment"] is None


async def test_extra_fields_and_bad_money_are_validation_errors(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc_id, _ = await to_accountant(client, staff)
    assert_error(await pay(client, staff["accountant"], doc_id, surprise=1), 422, "VALIDATION_FAILED")
    assert_error(
        await pay(client, staff["accountant"], doc_id, amount={"amount": "1500000", "currency": "UZS"}),
        422,
        "VALIDATION_FAILED",
    )


async def test_someone_elses_unattached_file_cannot_be_the_receipt(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc_id, _ = await to_accountant(client, staff)
    foreign = (await upload(client, staff["manager"])).json()
    assert_error(
        await pay(client, staff["accountant"], doc_id, receipt_file_id=foreign["id"]), 422, "VALIDATION_FAILED"
    )
    after = (await client.get(f"/api/v1/documents/{doc_id}", headers=staff["accountant"].headers)).json()
    assert after["status"] == "to_accountant"


async def test_accountant_author_cannot_pay_own_memo_while_another_holder_exists(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await seed_employee(container, 21, permissions={"eds": ["payments.confirm"]})
    doc = await create(client, staff["accountant"], **WITH_AMOUNT)
    approval_id = (await submit(client, staff["accountant"], doc["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], approval_id, "approve")).status_code == 200
    assert_error(await pay(client, staff["accountant"], doc["id"]), 403, "FORBIDDEN", reason="not_your_step")
    assert (await pay(client, headers_of(21), doc["id"])).status_code == 200


async def test_return_and_reject_still_work_on_the_accountant_step(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc_id, approval_id = await to_accountant(client, staff)
    returned = await decide(client, staff["accountant"], approval_id, "return", comment="Нет счёта поставщика")
    assert returned.status_code == 200
    doc = (await client.get(f"/api/v1/documents/{doc_id}", headers=staff["manager"].headers)).json()
    assert doc["status"] == "returned"
    assert_error(await pay(client, staff["accountant"], doc_id), 409, "CONFLICT", reason="invalid_state")


async def test_the_list_marks_files_and_the_paid_day(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    invoice = (await upload(client, staff["manager"], name="счёт поставщика.pdf", content=PDF)).json()
    doc_id, _ = await to_accountant(client, staff, file_ids=[invoice["id"]])
    page = (
        await client.get("/api/v1/documents", params={"status": "to_accountant"}, headers=staff["accountant"].headers)
    ).json()
    validate("DocumentPage", page)
    item = next(i for i in page["items"] if i["id"] == doc_id)
    assert item["files_count"] == 1 and item["paid_on"] is None
    await pay(client, staff["accountant"], doc_id)
    page = (
        await client.get("/api/v1/documents", params={"status": "paid"}, headers=staff["accountant"].headers)
    ).json()
    validate("DocumentPage", page)
    assert next(i for i in page["items"] if i["id"] == doc_id)["paid_on"] == today()
