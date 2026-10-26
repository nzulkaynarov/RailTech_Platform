"""Событие и изменение — одна транзакция (CONVENTIONS.md §2 п. 3): откат — ни события в outbox, ни строк, ни номера."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.bus.erp_snapshots import QuoteReady
from app.container import Container
from app.models import Employee
from app.schemas.approvals import DecisionIn
from app.schemas.documents import DocumentCreate, DocumentSubmitIn
from app.schemas.letters import LetterCreate, ResolutionIn
from app.services import approvals, documents, letters, quotes
from tests.domain import Person, erp_event, outbox
from tests.test_documents import WITH_AMOUNT, create, submit
from tests.test_letters import NEW_LETTER, RESOLUTION, register

pytestmark = pytest.mark.pg


class Abort(Exception):  # noqa: N818 — маркер намеренного отката в тесте
    pass


Op = Callable[[AsyncSession, AsyncBus, Employee], Awaitable[Any]]


async def counters(container: Container) -> tuple[int, dict[str, int], int]:
    """(событий в outbox, счётчики номеров, строк журнала) — всё, что откат обязан вернуть."""
    async with container.session_factory() as session:
        events = int((await session.execute(text("SELECT count(*) FROM rt_bus_outbox"))).scalar_one())
        rows = (await session.execute(text("SELECT kind || '/' || year, last_value FROM number_counters"))).all()
        journal = int((await session.execute(text("SELECT count(*) FROM journal"))).scalar_one())
    return events, {k: int(v) for k, v in rows}, journal


async def rolled_back(container: Container, employee_id: int, op: Op) -> None:
    """Выполнить операцию в транзакции и откатить её; ни событий, ни сдвига счётчиков, ни журнала после неё нет."""
    before = await counters(container)
    async with container.session_factory() as reader:
        employee = await reader.get(Employee, employee_id)
    assert employee is not None

    async def attempt() -> None:
        async with container.session_factory() as session, session.begin():
            await op(session, container.bus, employee)
            raise Abort

    with pytest.raises(Abort):
        await attempt()
    assert await counters(container) == before


async def test_registering_a_letter_rolled_back_leaves_no_event_row_or_number(
    container: Container, staff: dict[str, Person]
) -> None:
    async def op(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        letter = await letters.register(
            session, bus, actor_id=who.crm_user_id, data=LetterCreate.model_validate(NEW_LETTER)
        )
        assert letter.number == "ВХ-001/26"

    await rolled_back(container, 4, op)
    assert await outbox(container) == []
    async with container.session_factory() as session, session.begin():  # номер не потерян откатом
        letter = await letters.register(
            session, container.bus, actor_id=4, data=LetterCreate.model_validate(NEW_LETTER)
        )
        assert letter.number == "ВХ-001/26"
    assert len(await outbox(container, "letter.registered")) == 1


async def test_letter_decisions_rolled_back_publish_nothing(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter_id = uuid.UUID((await register(client, staff["registrar"]))["id"])

    async def resolve(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await letters.resolve(
            session, bus, actor_id=3, letter_id=letter_id, data=ResolutionIn.model_validate(RESOLUTION)
        )

    async def back(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await letters.return_letter(session, bus, actor_id=3, letter_id=letter_id, comment="Уточните")

    async def reject(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await letters.reject(session, bus, actor_id=3, letter_id=letter_id, reason="Нет")

    for op in (resolve, back, reject):
        await rolled_back(container, 3, op)
    assert len(await outbox(container)) == 1  # только исходная регистрация
    status = (await client.get(f"/api/v1/letters/{letter_id}", headers=staff["director"].headers)).json()["status"]
    assert status == "awaiting_resolution"


async def test_letter_from_erp_request_rolled_back(container: Container, staff: dict[str, Person]) -> None:
    async def op(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await letters.register_from_request(
            session,
            bus,
            moment=clock.now(),
            erp_company_id=1,
            crm_client_id=2,
            erp_deal_id=3,
            deal_number="ЗВ-2026-001",
            title="Заявка",
            erp_request_id=9,
            summary=None,
        )

    await rolled_back(container, 3, op)


async def test_document_creation_and_submission_rolled_back(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    async def make(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await documents.create(session, bus, employee=who, data=DocumentCreate.model_validate(WITH_AMOUNT))

    await rolled_back(container, 5, make)

    draft = await create(client, staff["manager"], **WITH_AMOUNT)
    letter_out = await create(client, staff["registrar"], kind="letter_out", recipient={"name": "ООО «Адресат»"})
    before = len(await outbox(container))

    async def send_for_approval(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await documents.submit(session, bus, employee=who, document_id=uuid.UUID(draft["id"]), edits=DocumentSubmitIn())

    async def send_letter(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await documents.submit(session, bus, employee=who, document_id=uuid.UUID(letter_out["id"]), edits=None)

    await rolled_back(container, 5, send_for_approval)
    await rolled_back(container, 4, send_letter)
    assert len(await outbox(container)) == before


async def test_decision_rolled_back_publishes_neither_decided_nor_archived(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    route_id = uuid.UUID((await submit(client, staff["manager"], doc["id"])).json()["approval_id"])

    async def approve(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await approvals.decide(session, bus, employee=who, route_id=route_id, body=DecisionIn(decision="approve"))

    await rolled_back(container, 3, approve)
    assert await outbox(container, "approval.decided") == []
    assert await outbox(container, "document.archived") == []
    status = (await client.get(f"/api/v1/documents/{doc['id']}", headers=staff["director"].headers)).json()["status"]
    assert status == "on_approval"


async def test_failure_of_a_later_event_rolls_back_the_whole_request(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`approval.decided` уже в outbox, но `document.archived` не записался: запрос падает, решение не сохраняется."""
    doc = await create(client, staff["manager"])
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    original = AsyncBus.publish

    async def failing(self: AsyncBus, session: AsyncSession, event_type: str, *args: Any, **kwargs: Any) -> Any:
        if event_type.endswith("document.archived.v1"):
            raise RuntimeError("шина недоступна")
        return await original(self, session, event_type, *args, **kwargs)

    monkeypatch.setattr(AsyncBus, "publish", failing)
    with pytest.raises(
        RuntimeError, match="шина недоступна"
    ):  # ASGI-транспорт теста пробрасывает исключение приложения
        await client.post(
            f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=staff["director"].headers
        )
    monkeypatch.undo()
    assert await outbox(container, "approval.decided") == []
    route = (await client.get(f"/api/v1/approvals/{approval_id}", headers=staff["director"].headers)).json()
    assert route["status"] == "open" and route["can_decide"] is True
    again = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=staff["director"].headers
    )
    assert again.status_code == 200
    assert len(await outbox(container, "approval.decided")) == 1


async def test_failing_publish_in_http_request_leaves_no_letter_and_keeps_the_number(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(*_: Any, **__: Any) -> Any:
        raise RuntimeError("шина недоступна")

    monkeypatch.setattr(AsyncBus, "publish", failing)
    with pytest.raises(RuntimeError, match="шина недоступна"):
        await client.post("/api/v1/letters", json=NEW_LETTER, headers=staff["registrar"].headers)
    monkeypatch.undo()
    assert (await client.get("/api/v1/letters", headers=staff["director"].headers)).json()["items"] == []
    assert (await register(client, staff["registrar"]))["number"] == "ВХ-001/26"


async def test_quote_route_rolled_back(container: Container, staff: dict[str, Person]) -> None:
    data = QuoteReady.model_validate(erp_event("erp/quote.ready_for_approval.v1")["data"])

    async def op(session: AsyncSession, bus: AsyncBus, who: Employee) -> None:
        await quotes.open_for_quote(session, bus, data)

    await rolled_back(container, 3, op)
    assert await outbox(container) == []
