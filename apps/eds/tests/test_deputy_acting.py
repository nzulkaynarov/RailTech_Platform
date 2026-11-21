"""СЦ-9 P11 (pg): заместитель решает шаги замещаемого — служебки, КП, поручения и переносы срока; подпись и оплата не
переходят; вне периода и без замещения — отказ. Решение владельца 2026-11-21 (2)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text

from app.container import Container
from app.models import ApprovalRoute, ApprovalStep, Employee
from app.services import access
from tests.domain import Person
from tests.test_api_auth import assert_error
from tests.test_documents import WITH_AMOUNT, create, decide, route_of, submit
from tests.test_letter_instructions import BANK, DUE, act, register, resolve
from tests.test_quotes import only_route, ready, resolve_letter

pytestmark = pytest.mark.pg

# Часы тестов: 2026-10-26. Период охватывает сегодня; «просрочен» — закончился накануне.
ACTIVE = ("2026-10-20", "2026-10-26")
EXPIRED = ("2026-10-12", "2026-10-25")


async def cover(container: Container, absent: int, deputy: int | None, period: tuple[str, str] = ACTIVE) -> None:
    """Проекция замещения (`employees.deputy_*`), как после `identity.user.updated` с полем `deputy`."""
    async with container.session_factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE employees SET deputy_crm_user_id = :d, deputy_from = :f, deputy_to = :t WHERE crm_user_id = :a"
            ),
            {"d": deputy, "f": period[0], "t": period[1], "a": absent},
        )


async def memo_route(client: httpx.AsyncClient, staff: dict[str, Person], **body: Any) -> tuple[dict[str, Any], str]:
    doc = await create(client, staff["manager"], **body)
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    return doc, str(approval_id)


# --- служебка: видит, открывает, решает, журнал «за» ----------------------------------------------------------------


async def test_deputy_sees_and_decides_directors_memo_and_journal_says_on_behalf(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    deputy = staff["registrar"]
    await cover(container, 3, deputy.id)
    doc, approval_id = await memo_route(client, staff)

    page = (await client.get("/api/v1/approvals", headers=deputy.headers)).json()
    [item] = page["items"]
    assert item["id"] == approval_id
    assert item["acting_for"] == {"crm_user_id": 3, "full_name": "Рустам Директоров"}
    # документ виден: заместитель открывает то, что ему решать
    assert (await client.get(f"/api/v1/documents/{doc['id']}", headers=deputy.headers)).status_code == 200

    card = await route_of(client, deputy, approval_id)
    assert (card["can_decide"], card["acting_for"]["crm_user_id"]) == (True, 3)
    assert card["allowed_decisions"] == ["approve", "return", "reject"]
    # директор свой шаг видит без пометки
    own = (await client.get("/api/v1/approvals", headers=staff["director"].headers)).json()["items"]
    assert [i["acting_for"] for i in own] == [None]

    done = await decide(client, deputy, approval_id, "approve")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "approved"
    journal = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["director"].headers)).json()["journal"]
    decided = next(e for e in journal if e["action"] == "approval.decided")
    assert decided["by"]["crm_user_id"] == deputy.id
    assert decided["on_behalf_of"] == {"crm_user_id": 3, "full_name": "Рустам Директоров"}
    assert all(e["on_behalf_of"] is None for e in journal if e["action"] != "approval.decided")


async def test_no_deputyship_refuses_everything(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    other = staff["registrar"]
    doc, approval_id = await memo_route(client, staff)
    assert (await client.get("/api/v1/approvals", headers=other.headers)).json()["items"] == []
    assert_error(await decide(client, other, approval_id, "approve"), 403, "FORBIDDEN")
    assert (await client.get(f"/api/v1/documents/{doc['id']}", headers=other.headers)).status_code == 404


async def test_expired_period_and_inactive_replaced_refuse(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    deputy = staff["registrar"]
    await cover(container, 3, deputy.id, EXPIRED)
    doc, approval_id = await memo_route(client, staff)
    assert (await client.get("/api/v1/approvals", headers=deputy.headers)).json()["items"] == []
    assert_error(await decide(client, deputy, approval_id, "approve"), 403, "FORBIDDEN")
    assert (await client.get(f"/api/v1/documents/{doc['id']}", headers=deputy.headers)).status_code == 404
    # период вот-вот начнётся: завтра — ещё не замещает
    await cover(container, 3, deputy.id, ("2026-10-27", "2026-10-30"))
    assert (await client.get("/api/v1/approvals", headers=deputy.headers)).json()["items"] == []
    # отключённый сотрудник не замещается
    await cover(container, 3, deputy.id)
    async with container.session_factory() as session, session.begin():
        await session.execute(text("UPDATE employees SET is_active = false WHERE crm_user_id = 3"))
    assert (await client.get("/api/v1/approvals", headers=deputy.headers)).json()["items"] == []


async def test_deputy_does_not_decide_the_replaced_persons_own_document(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    deputy = staff["registrar"]
    await cover(container, 3, deputy.id)
    doc = await create(client, staff["director"], subject="Служебка директора")
    approval_id = (await submit(client, staff["director"], doc["id"])).json()["approval_id"]
    assert (await client.get("/api/v1/approvals", headers=deputy.headers)).json()["items"] == []
    assert_error(await decide(client, deputy, approval_id, "approve"), 404, "NOT_FOUND")


async def test_deputy_decision_still_refuses_own_document_of_the_deputy(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Разделение обязанностей: заместитель не решает служебку, адресованную замещаемому, если автор — он сам."""
    deputy = staff["manager"]
    await cover(container, 3, deputy.id)
    body = {"kind": "memo", "subject": "Моя", "text": "Текст", "addressee_crm_user_id": 3}
    doc = (await client.post("/api/v1/documents", json=body, headers=deputy.headers)).json()
    approval_id = (await submit(client, deputy, doc["id"])).json()["approval_id"]
    assert_error(await decide(client, deputy, approval_id, "approve"), 403, "FORBIDDEN", reason="not_your_step")


# --- оплата не переходит --------------------------------------------------------------------------------------------


async def test_payment_step_does_not_pass_to_the_deputy_of_the_accountant(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    deputy = staff["engineer"]
    await cover(container, 6, deputy.id)
    await cover(container, 3, deputy.id)
    doc, approval_id = await memo_route(client, staff, **WITH_AMOUNT)
    assert (await decide(client, deputy, approval_id, "approve")).status_code == 200  # шаг директора — за директора
    assert (await client.get("/api/v1/approvals", headers=deputy.headers)).json()["items"] == []
    assert_error(await decide(client, deputy, approval_id, "approve"), 403, "FORBIDDEN", reason="not_your_step")
    paid = await client.post(
        f"/api/v1/documents/{doc['id']}/payment",
        json={"paid_on": "2026-10-26", "amount": {"amount": "1500000.00", "currency": "UZS"}},
        headers=deputy.headers,
    )
    assert paid.status_code == 403, paid.text
    # бухгалтер сам по-прежнему видит свой шаг
    mine = (await client.get("/api/v1/approvals", headers=staff["accountant"].headers)).json()["items"]
    assert [i["acting_for"] for i in mine] == [None]


# --- подпись не переходит -------------------------------------------------------------------------------------------


async def test_signing_route_never_passes_to_the_deputy(container: Container, staff: dict[str, Person]) -> None:
    await cover(container, 3, 11)
    async with container.session_factory() as session, session.begin():
        route = ApprovalRoute(
            id=uuid.uuid4(),
            template="signing",
            title="Договор",
            status="open",
            round=1,
            current_step=1,
            created_at=datetime(2026, 10, 26, tzinfo=UTC),
        )
        session.add(route)
        await session.flush()
        for index, (user, permission) in enumerate([(3, None), (None, "memos.approve")], start=1):
            session.add(
                ApprovalStep(
                    approval_id=route.id,
                    index=index,
                    label="Подписать",
                    assignee_crm_user_id=user,
                    assignee_permission=permission,
                    status="current" if index == 1 else "pending",
                )
            )
    async with container.session_factory() as session:
        emp = await session.get(Employee, 11)
        assert emp is not None
        assert (await access.acting_on_behalf(session, emp, owner=3, template="signing")).allowed is False
        seen = (await session.execute(select(ApprovalStep.index).where(access.step_is_mine(emp)))).all()
        assert seen == []  # ни личный шаг подписи, ни шаг по праву не стали «моими» у заместителя
        director = await session.get(Employee, 3)
        assert director is not None
        assert len((await session.execute(select(ApprovalStep.index).where(access.step_is_mine(director)))).all()) == 2


async def test_acting_on_behalf_rules(container: Container, staff: dict[str, Person]) -> None:
    await cover(container, 3, 11)
    async with container.session_factory() as session:
        me = await session.get(Employee, 11)
        assert me is not None

        async def who(**kw: Any) -> access.Acting:
            return await access.acting_on_behalf(session, me, **kw)

        assert (await who(owner=11)).on_behalf_of is None and (await who(owner=11)).allowed
        taken = await who(owner=3, template="memo")
        assert taken.allowed and taken.on_behalf_of is not None and taken.on_behalf_of.crm_user_id == 3
        assert (await who(permission="memos.approve", template="quote")).allowed
        assert (await who(permission="approvals.decide", template="quote")).allowed
        assert (await who(owner=3, template=access.INSTRUCTION)).allowed
        assert not (await who(owner=3, template="signing")).allowed
        assert not (await who(permission="payments.confirm", template="memo")).allowed
        assert not (await who(owner=4, template="memo")).allowed  # чужой шаг незамещаемого
        assert not (await who(permission="letters.resolve", template="memo")).allowed  # не из переходящих


# --- КП ------------------------------------------------------------------------------------------------------------


async def test_deputy_decides_quote_approval(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    deputy = staff["registrar"]
    await cover(container, 3, deputy.id)
    await resolve_letter(client, staff, "15")
    await ready(client, container, eds_letter_id=None)
    route = await only_route(client, deputy)
    assert (route["can_decide"], route["acting_for"]["crm_user_id"]) == (True, 3)
    approved = await client.post(
        f"/api/v1/approvals/{route['id']}/decision",
        json={"decision": "approve", "channels": ["cabinet"]},
        headers=deputy.headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


# --- поручения и перенос срока --------------------------------------------------------------------------------------


async def instruction_for_supplier(client: httpx.AsyncClient, staff: dict[str, Person]) -> dict[str, Any]:
    letter = await register(client, staff["registrar"], BANK, addressee_crm_user_id=3)
    draft = {"kind": "execute", "responsible_crm_user_id": 11, "due": DUE, "text": "Ответить банку."}
    body = (await resolve(client, staff["director"], letter["id"], **draft)).json()
    [instruction] = body["instructions"]
    return instruction  # type: ignore[no-any-return]


async def test_deputy_executes_instruction_and_asks_extension_for_the_executor(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    deputy, executor = staff["engineer"], staff["supplier"]
    instruction = await instruction_for_supplier(client, staff)
    await cover(container, executor.id, deputy.id)

    tasks = (await client.get("/api/v1/letter-tasks", headers=deputy.headers)).json()
    [task] = tasks["instructions"]
    assert (task["id"], task["acting_for"]["crm_user_id"]) == (instruction["id"], executor.id)
    mine = (await client.get("/api/v1/letter-tasks", headers=executor.headers)).json()
    assert [t["acting_for"] for t in mine["instructions"]] == [None]

    asked = await act(client, deputy, instruction["id"], "extension", {"new_due": "2026-11-09", "reason": "Ждём банк"})
    assert asked.status_code == 200, asked.text
    done = await act(client, deputy, instruction["id"], "complete", {"report": "Сделано заместителем."})
    assert done.status_code == 200, done.text
    journal = done.json()["journal"]
    entry = next(e for e in journal if e["action"] == "instruction.executed")
    assert entry["by"]["crm_user_id"] == deputy.id and entry["on_behalf_of"]["crm_user_id"] == executor.id


async def test_deputy_of_resolution_author_decides_extension(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    deputy = staff["registrar"]
    instruction = await instruction_for_supplier(client, staff)
    assert (
        await act(client, staff["supplier"], instruction["id"], "extension", {"new_due": "2026-11-09", "reason": "x"})
    ).status_code == 200
    await cover(container, 3, deputy.id)
    tasks = (await client.get("/api/v1/letter-tasks", headers=deputy.headers)).json()
    [ext] = tasks["extensions"]
    assert ext["acting_for"]["crm_user_id"] == 3
    rejected = await act(client, deputy, instruction["id"], "extension/decision", {"decision": "reject"})
    assert rejected.status_code == 200, rejected.text
    entry = next(e for e in rejected.json()["journal"] if e["action"] == "instruction.extension_rejected")
    assert (entry["by"]["crm_user_id"], entry["on_behalf_of"]["crm_user_id"]) == (deputy.id, 3)


async def test_instruction_actions_refused_without_deputyship_or_after_period(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    other, executor = staff["engineer"], staff["supplier"]
    instruction = await instruction_for_supplier(client, staff)
    assert_error(
        await act(client, other, instruction["id"], "complete", {"report": "Я"}),
        403,
        "FORBIDDEN",
        reason="not_executor",
    )
    await cover(container, executor.id, other.id, EXPIRED)
    assert (await client.get("/api/v1/letter-tasks", headers=other.headers)).json()["instructions"] == []
    assert_error(
        await act(client, other, instruction["id"], "extension", {"new_due": "2026-11-09", "reason": "x"}),
        403,
        "FORBIDDEN",
        reason="not_executor",
    )
    assert_error(
        await act(client, other, instruction["id"], "extension/decision", {"decision": "reject"}),
        403,
        "FORBIDDEN",
        reason="not_resolution_author",
    )
