"""Сигналы о задачах «Главной» (ГЛ-2, pg): задача пришла к сотруднику — одно уведомление; ничего лишнего автору и
тому, кто запустил шаг. Тексты и получатели выводятся из шага маршрута и письма — тех же фактов, что строка очереди."""

import json
from typing import Any

import httpx
import jsonschema
import pytest
from referencing import Registry, Resource

from app.container import Container
from tests.domain import Person, deliver_erp, outbox
from tests.helpers import EVENTS
from tests.test_commercial_signing import _grant_director, _open_ids, _pass_visas, _request
from tests.test_documents import WITH_AMOUNT, create, decide, submit
from tests.test_letters import register
from tests.test_payments import to_accountant
from tests.test_quotes import ready

pytestmark = pytest.mark.pg

TASK_KINDS = {
    "approve_quote",
    "resolve_letter",
    "approve_memo",
    "pay_memo",
    "sign_commercial",
    "visa_commercial",
    "rework_document",
}


def _registry() -> Any:
    registry = Registry()
    for name in ("_defs.v1.json", "_defs.v2.json"):
        defs = json.loads((EVENTS / "eds" / name).read_text(encoding="utf-8"))
        registry = registry.with_resource(defs["$id"], Resource.from_contents(defs))
    return registry


async def tasks(container: Container, kind: str | None = None) -> list[dict[str, Any]]:
    schema = json.loads((EVENTS / "eds" / "document.notice_requested.v2.json").read_text(encoding="utf-8"))
    found = [e["data"] for e in await outbox(container, "document.notice_requested")]
    for data in found:
        jsonschema.Draft202012Validator(
            schema, registry=_registry(), format_checker=jsonschema.FormatChecker()
        ).validate(data)
    return [d for d in found if d["kind"] in TASK_KINDS and (kind is None or d["kind"] == kind)]


async def test_memo_sent_for_approval_signals_the_director_and_not_the_author(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    assert await tasks(container) == []  # черновик — никому
    await submit(client, staff["manager"], doc["id"])

    [notice] = await tasks(container)
    assert notice["kind"] == "approve_memo" and notice["recipients"] == [3]  # директор, не автор (5)
    assert notice["title"] == f"Согласуйте: Служебка {doc['number']}"
    assert notice["document"]["eds_document_id"] == doc["id"]
    assert notice["notice_key"].endswith(":s1:approve_memo")


async def test_memo_with_amount_reaches_the_accountant_when_the_director_approves(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await to_accountant(client, staff, **WITH_AMOUNT)

    kinds = [(n["kind"], n["recipients"]) for n in await tasks(container)]
    assert kinds == [("approve_memo", [3]), ("pay_memo", [6])]  # бухгалтер узнаёт, когда шаг стал его
    keys = [n["notice_key"] for n in await tasks(container)]
    assert len(set(keys)) == 2  # шаг — один ключ: повтор доставки не размножит строку


async def test_returned_document_signals_only_the_author(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    doc = await create(client, staff["manager"])
    approval_id = (await submit(client, staff["manager"], doc["id"])).json()["approval_id"]
    assert (await decide(client, staff["director"], approval_id, "return", comment="Уточните сумму")).status_code == 200

    [notice] = await tasks(container, "rework_document")
    assert notice["recipients"] == [5]
    assert notice["subtitle"] == "Вернул Рустам Директоров: Уточните сумму"
    assert notice["document"]["eds_document_id"] == doc["id"]


async def test_quote_for_approval_signals_the_holders_of_the_decision_right_once(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await ready(client, container)
    [notice] = await tasks(container, "approve_quote")
    assert 3 in notice["recipients"]
    assert notice["approval"]["template"] == "quote" and notice["title"].startswith("КП на одобрение: ")
    await ready(client, container)  # повтор события ERP: круг прежний, уведомления второго нет
    assert len(await tasks(container, "approve_quote")) == 1


async def test_contract_visas_then_signature_each_signal_their_own_holder(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await _grant_director(client, staff)
    await deliver_erp(client, container, _request(staff))
    [approval_id] = await _open_ids(client, staff)

    [visa] = await tasks(container)
    assert visa["kind"] == "visa_commercial" and visa["recipients"] == [6]  # бухгалтер; юрист — когда придёт его шаг
    await _pass_visas(client, staff, approval_id)

    assert [(n["kind"], n["recipients"]) for n in await tasks(container)] == [
        ("visa_commercial", [6]),
        ("visa_commercial", [staff["lawyer"].id]),
        ("sign_commercial", [3]),
    ]
    assert all(n["approval"]["eds_approval_id"] == approval_id for n in await tasks(container))


async def test_inbound_letter_awaiting_resolution_signals_the_addressee(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    letter = await register(client, staff["registrar"])
    [notice] = await tasks(container, "resolve_letter")
    assert notice["recipients"] == [3]  # адресат по умолчанию — директор; делопроизводитель, регистрировавший, — нет
    assert notice["letter"]["eds_letter_id"] == letter["id"]
    assert notice["notice_key"] == f"letter:{letter['id']}:resolve_letter"
