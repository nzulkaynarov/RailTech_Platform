"""Документы проектов из ERP в реестре «Все документы» (pg, D2-5): проекция по событиям шины, статусы, видимость.

Договор, счёт и акт — владелец ERP; EDS хранит строку на документ по событиям `erp.contract.status_changed`,
`erp.invoice.*`, `erp.act.*`. Проверяется: строка появляется и обновляется статусом (слова SPEC-v3 §2.4), повтор события
безвреден, более старое событие не затирает новое, клиент и ответственный берутся из письма по заявке, реестр отдаёт их
только держателю `registry.read`, вкладка и экспорт работают, ответ соответствует схеме `RegistryPage`.
"""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.container import Container
from tests.domain import Person, deliver_erp, erp_event
from tests.helpers import example, iso
from tests.test_api_auth import assert_error
from tests.test_registry import listing

pytestmark = pytest.mark.pg

T0 = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)


def contract_event(status: str, *, at: datetime = T0, **payload: Any) -> dict[str, Any]:
    envelope = erp_event("erp/contract.status_changed.v1", status=status, **payload)
    envelope["time"] = iso(at)
    return envelope


def at(envelope: dict[str, Any], moment: datetime) -> dict[str, Any]:
    envelope["time"] = iso(moment)
    return envelope


async def rows(client: httpx.AsyncClient, who: Person, **params: Any) -> list[dict[str, Any]]:
    return await listing(client, who, **params)


async def test_contract_event_appears_in_the_registry_with_the_spec_status(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    assert await deliver_erp(client, container, contract_event("issued_at_operator")) == "processed"
    [item] = await rows(client, staff["accountant"], kind="contract")
    assert (item["kind"], item["number"], item["status"]) == ("contract", "ДОГ-2026/118", "issued_at_operator")
    assert item["title"] == "Поставка оборудования, партия 1"
    assert item["links"]["erp_deal_id"] == 905 and item["links"]["deal_number"] == "D-2026-0905"
    assert item["links"]["crm_client_id"] == 42 and item["links"]["erp_company_id"] == 118
    assert item["responsible"] is None and item["client"] is None, "письма по заявке нет — клиента и ответственного нет"


async def test_client_and_responsible_come_from_the_letter_of_the_same_request(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, erp_event("erp/request.created.v1"))
    await deliver_erp(client, container, contract_event("project", sent_to_client=False))
    [item] = await rows(client, staff["manager"], kind="contract")
    assert item["client"] == {"name": "ООО «Пример Логистик»", "inn": "301234567"}
    assert item["responsible"] == {"crm_user_id": 5, "full_name": "Алия Каримова"}
    assert await rows(client, staff["manager"], kind="contract", responsible=5) == [item]
    assert await rows(client, staff["manager"], kind="contract", responsible=99) == []


@pytest.mark.parametrize(
    "status", ["project", "client_agreed", "issued_at_operator", "signed", "rejected", "cancelled"]
)
async def test_every_contract_status_is_projected(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], status: str
) -> None:
    await deliver_erp(client, container, contract_event(status))
    [item] = await rows(client, staff["director"], kind="contract")
    assert item["status"] == status


async def test_status_moves_forward_and_one_row_stays(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, contract_event("project", at=T0))
    await deliver_erp(client, container, contract_event("client_agreed", at=T0 + timedelta(hours=1)))
    await deliver_erp(client, container, contract_event("signed", at=T0 + timedelta(hours=2)))
    [item] = await rows(client, staff["accountant"], kind="contract")
    assert item["status"] == "signed"
    assert item["registered_at"].startswith("2026-10-28T06:00"), "дата регистрации — первого события"


async def test_an_older_event_does_not_overwrite_a_newer_status(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, contract_event("signed", at=T0 + timedelta(hours=2)))
    await deliver_erp(client, container, contract_event("client_agreed", at=T0))
    [item] = await rows(client, staff["accountant"], kind="contract")
    assert item["status"] == "signed"


async def test_repeat_of_the_same_event_is_harmless(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    first = contract_event("client_agreed")
    await deliver_erp(client, container, first)
    assert await deliver_erp(client, container, first) == "processed"
    again = contract_event("client_agreed")  # другой id события, то же состояние
    await deliver_erp(client, container, again)
    assert len(await rows(client, staff["accountant"], kind="contract")) == 1


async def test_invoice_and_act_events_are_projected(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, at(erp_event("erp/invoice.issued.v1"), T0))
    await deliver_erp(client, container, at(erp_event("erp/act.issued.v1"), T0))
    invoices = await rows(client, staff["accountant"], kind="invoice")
    acts = await rows(client, staff["accountant"], kind="act")
    assert [(i["number"], i["status"]) for i in invoices] == [("СЧ-2026-0441", "issued")]
    assert [(a["number"], a["status"]) for a in acts] == [("АКТ-2026-0052", "issued")]

    await deliver_erp(
        client, container, at(erp_event("erp/invoice.paid.v1", erp_invoice_id=4410), T0 + timedelta(days=1))
    )
    await deliver_erp(
        client,
        container,
        at(erp_event("erp/act.returned.v1", erp_act_id=520, reason="Опечатка"), T0 + timedelta(hours=1)),
    )
    await deliver_erp(client, container, at(erp_event("erp/act.accepted.v1", erp_act_id=520), T0 + timedelta(hours=2)))
    assert [i["status"] for i in await rows(client, staff["accountant"], kind="invoice")] == ["paid"]
    assert [a["status"] for a in await rows(client, staff["accountant"], kind="act")] == ["signed"]


async def test_overdue_invoice_and_returned_act_have_their_own_words(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, erp_event("erp/invoice.overdue.v1"))
    await deliver_erp(client, container, erp_event("erp/act.returned.v1"))
    assert [i["status"] for i in await rows(client, staff["director"], kind="invoice")] == ["overdue"]
    assert [i["status"] for i in await rows(client, staff["director"], kind="act")] == ["returned"]


async def test_all_documents_tab_mixes_project_documents_with_the_rest(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, contract_event("project"))
    await deliver_erp(client, container, erp_event("erp/invoice.issued.v1"))
    kinds = {i["kind"] for i in await rows(client, staff["director"])}
    assert {"contract", "invoice"} <= kinds
    assert [i["kind"] for i in await rows(client, staff["director"], kind=["contract", "act"])] == ["contract"]
    assert [i["number"] for i in await rows(client, staff["director"], q="СЧ-2026")] == ["СЧ-2026-0441"]
    assert [i["number"] for i in await rows(client, staff["director"], number="ДОГ-2026/118")] == ["ДОГ-2026/118"]
    assert await rows(client, staff["director"], status=["signed"]) == []


@pytest.mark.parametrize("who", ["director", "manager", "accountant", "supplier", "engineer"])
async def test_every_holder_of_registry_read_sees_the_project_documents(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], who: str
) -> None:
    await deliver_erp(client, container, contract_event("signed"))
    assert len(await rows(client, staff[who], kind="contract")) == 1


@pytest.mark.parametrize("who", ["registrar", "admin", "nobody"])
async def test_without_registry_read_there_is_no_registry_at_all(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person], who: str
) -> None:
    await deliver_erp(client, container, contract_event("signed"))
    response = await client.get("/api/v1/registry", params={"kind": "contract"}, headers=staff[who].headers)
    assert_error(response, 403, "FORBIDDEN")
    export = await client.get("/api/v1/registry/export", params={"kind": "contract"}, headers=staff[who].headers)
    assert export.status_code == 403


async def test_project_documents_are_not_shown_where_registry_read_is_withdrawn(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Даже если `registry.read` снят, а сотрудник остался автором чужих документов, проекции договоров ему не видны."""
    from app.services import registry

    await deliver_erp(client, container, contract_event("signed"))
    async with container.session_factory() as session:
        employee = await session.get(__import__("app.models", fromlist=["Employee"]).Employee, staff["registrar"].id)
        assert employee is not None
        page = await registry.list_page(session, employee, registry.Filters(), cursor=None, limit=50)
    assert page.items == []


async def test_event_without_the_document_id_is_rejected_at_the_door(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """Схема типа требует `erp_contract_id`: событие без него приёмник не принимает (422/400), строки нет."""
    from tests.conftest import BUS_SECRET_ERP_EDS
    from tests.helpers import signed

    envelope = contract_event("signed")
    del envelope["data"]["payload"]["erp_contract_id"]
    headers, body = signed(envelope, publisher="erp", secret=BUS_SECRET_ERP_EDS)
    response = await client.post("/bus/v1/events", headers=headers, content=body)
    assert response.status_code in (400, 422)
    assert await rows(client, staff["director"], kind="contract") == []


async def test_unknown_future_fields_are_tolerated(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    envelope = copy.deepcopy(contract_event("signed"))
    envelope["data"]["payload"]["something_new"] = {"x": 1}
    envelope["data"]["deal"]["another"] = 1
    assert await deliver_erp(client, container, envelope) == "processed"
    assert len(await rows(client, staff["director"], kind="contract")) == 1


async def test_export_contains_project_documents(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await deliver_erp(client, container, contract_event("signed"))
    response = await client.get(
        "/api/v1/registry/export", params={"kind": "contract", "format": "csv"}, headers=staff["accountant"].headers
    )
    assert response.status_code == 200
    body = response.content.decode("utf-8-sig")
    assert "contract" in body and "ДОГ-2026/118" in body and "signed" in body


async def test_no_own_pdf_is_called_a_vat_invoice(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    """SPEC-v3 §2.1: «счёт-фактура» — только у оператора ЭДО; в проекции и в схеме реестра слова нет."""
    await deliver_erp(client, container, erp_event("erp/invoice.issued.v1"))
    [item] = await rows(client, staff["director"], kind="invoice")
    assert "фактур" not in str(item).lower()
    async with container.session_factory() as session:
        values = (await session.execute(text("SELECT title, number FROM project_documents"))).all()
    assert all("фактур" not in " ".join(row).lower() for row in values)


def test_the_example_of_the_new_event_is_valid_for_the_service() -> None:
    envelope = example("erp/contract.status_changed.v1")
    assert envelope["type"] == "uz.railtech.erp.contract.status_changed.v1"
    assert envelope["data"]["payload"]["status"] == "issued_at_operator"
