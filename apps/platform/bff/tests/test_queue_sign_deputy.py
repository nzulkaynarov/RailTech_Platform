"""СЦ-9: «Подписать» в «Моих задачах» и строки замещаемого «за {имя}».

Кому подписывать и чьи шаги решает заместитель — решает EDS (`signatures`, `acting_for`); BFF
показывает то, что вернул EDS, и не режет строки по роли. Исходящее не регистрируется без подписи:
строки `register_reply` нет, даже если старый EDS её прислал.
"""

from typing import Any

import pytest

from tests.conftest import ContractChecker, Web
from tests.feeds_support import FeedBackends, Moments
from tests.roles import rid
from tests.test_feeds_eds import page, route

DOC = "70000000-0000-4000-8000-000000000071"
SIGN_ROUTE = "80000000-0000-4000-8000-000000000081"
MADINA = {"crm_user_id": 12, "full_name": "Мадина Р."}


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


def signature(**over: Any) -> dict[str, Any]:
    return {
        "document_id": DOC,
        "subject": "Пояснения по требованию",
        "in_reply_to": {
            "id": "40000000-0000-4000-8000-000000000112",
            "number": "ВХ-112/26",
            "subject": "Требование ГНК о пояснениях",
        },
        "requested_by": {"crm_user_id": 7, "full_name": "Иван Исполнитель"},
        "requested_at": "2027-01-14T05:00:00Z",
        "acting_for": None,
        **over,
    }


def letter_tasks(**over: Any) -> dict[str, Any]:
    return {"instructions": [], "extensions": [], "acquaintances": [], "signatures": [], **over}


def signing_route(
    kind: str = "contract", number: str = "CT-2026-014", **over: Any
) -> dict[str, Any]:
    return {
        "id": SIGN_ROUTE,
        "template": "signing",
        "title": "Договор поставки · Демо-Рейл",
        "object": {
            "kind": "signing",
            "signing_kind": kind,
            "signing_number": number,
            "signing_amount_tiyins": 1_250_000_000,
            "signing_currency": "UZS",
        },
        "status": "open",
        "round": 1,
        "current_step": {
            "index": 1,
            "label": "Подписать",
            "status": "current",
            "assignee": {"crm_user_id": 3, "permission": None},
        },
        "acting_for": None,
        "created_at": "2027-01-14T04:00:00Z",
        **over,
    }


async def test_letter_signature_row_goes_to_whoever_eds_returned_it_to(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["letter_tasks"] = letter_tasks(signatures=[signature(), signature()])
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    [row] = [i for i in response.json()["items"] if i["kind"] == "sign_document"]
    assert row["id"] == f"sign_document:{DOC}"
    assert row["title"] == "Подписать исходящее: ответ на ВХ-112/26"
    assert row["subtitle"] == "Пояснения по требованию · Иван Исполнитель"
    assert row["due_label"] == "today"
    assert row["role_id"] == rid("DIRECTOR")
    assert "on_behalf_of" not in row
    assert row["object"] == {
        "kind": "memo",
        "number": "ВХ-112/26",
        "title": "Пояснения по требованию",
        "path": f"/eds/documents?scope=all&doc={DOC}&panel=open",
    }

    # роль строку не режет: подписанта выбрал EDS; а «Зарегистрировать исходящее» не бывает совсем
    await web.login(["SUPPLY"])
    items = (await web.client.get("/api/v1/queue")).json()["items"]
    assert [i["kind"] for i in items if i["kind"] in ("sign_document", "register_reply")] == [
        "sign_document"
    ]


async def test_letter_without_incoming_and_old_eds_registrations_are_not_a_row(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["letter_tasks"] = letter_tasks(signatures=[signature(in_reply_to=None)])
    fb.state["letter_tasks"]["registrations"] = [signature(document_id="x", acting_for=None)]
    await web.login(["REGISTRAR"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]

    [row] = [i for i in items if i["kind"] in ("sign_document", "register_reply")]
    assert row["kind"] == "sign_document"
    assert row["title"] == "Подписать исходящее: Пояснения по требованию"
    assert row["object"]["number"] == "Пояснения по требованию"


async def test_commercial_signing_step_is_a_sign_document_row_visa_is_not(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    visa = signing_route(
        "invoice",
        "INV-2026-031",
        id="80000000-0000-4000-8000-000000000082",
        current_step={
            "index": 1,
            "label": "Виза бухгалтера",
            "status": "current",
            "assignee": {"crm_user_id": None, "permission": "approvals.visa_finance"},
        },
    )
    fb.state["signing"] = page(signing_route(), visa)
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    [row] = [i for i in response.json()["items"] if i["kind"] == "sign_document"]
    assert row["id"] == f"sign_document:{SIGN_ROUTE}"
    assert row["title"] == "Подписать договор CT-2026-014"
    assert row["subtitle"].startswith(
        "Договор поставки · Демо-Рейл · 12\u00a0500\u00a0000\u00a0сум"
    )
    assert row["object"]["kind"] == "contract"
    assert row["object"]["path"] == f"/dashboard/queue?signing={SIGN_ROUTE}"
    template = fb.eds["approvals"].calls.last.request.url.params
    assert template.get("mine") == "true"
    assert template.get("status") == "open"


async def test_deputy_sees_replaced_steps_marked_even_without_the_role_for_them(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    """Заместитель менеджера-роли без права согласования получает шаги замещаемого, которые вернул
    EDS (`acting_for`): служебка, поручение, перенос срока, подпись. Пометка «за {имя}», id с
    суффиксом, роль — первая роль заместителя (RoleId контракта)."""
    covered = {**route("СЗ-2026/031"), "acting_for": MADINA}
    covered["current_step"]["assignee"] = {"crm_user_id": None, "permission": "memos.approve"}
    fb.state["memos"] = page(covered)
    fb.state["covering"] = [
        {
            "user_id": 12,
            "full_name": "Мадина Р.",
            "date_from": "2027-01-10",
            "date_to": "2027-01-20",
        }
    ]
    fb.state["letter_tasks"] = letter_tasks(
        signatures=[signature(acting_for=MADINA)],
        extensions=[
            {
                "id": "60000000-0000-4000-8000-000000000001",
                "instruction_id": "60000000-0000-4000-8000-000000000002",
                "letter": {
                    "id": "40000000-0000-4000-8000-000000000112",
                    "number": "ВХ-112/26",
                    "subject": "Требование",
                    "sender_name": "ГНК",
                },
                "executor": {"crm_user_id": 7, "full_name": "Иван Исполнитель"},
                "old_due": "2027-01-16",
                "new_due": "2027-01-22",
                "reason": "Ждём выписку",
                "acting_for": MADINA,
                "requested_at": "2027-01-14T04:00:00Z",
            }
        ],
    )
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    items = {i["kind"]: i for i in response.json()["items"] if i.get("on_behalf_of")}
    assert set(items) == {"approve_memo", "sign_document", "instruction_extension"}
    memo = items["approve_memo"]
    assert memo["id"] == "memo:50000000-0000-4000-8000-000000000031:for:12"
    assert memo["title"].startswith("Согласовать СЗ-2026/031")
    assert memo["on_behalf_of"] == {"id": "12", "name": "Мадина Р."}
    assert memo["role_id"] == rid("MANAGER")
    assert items["sign_document"]["id"] == f"sign_document:{DOC}:for:12"
    # рабочий экран поручения и переноса узнаёт, за кого он открыт, из адреса
    path = items["instruction_extension"]["object"]["path"]
    assert path.endswith("?for=12&forName=%D0%9C%D0%B0%D0%B4%D0%B8%D0%BD%D0%B0%20%D0%A0.")


async def test_without_covering_the_replaced_steps_are_not_read(web: Web, fb: FeedBackends) -> None:
    fb.state["memos"] = page({**route("СЗ-2026/031"), "acting_for": MADINA})
    await web.login(["MANAGER"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]

    assert [i for i in items if i["kind"] == "approve_memo"] == []
    assert fb.calls(fb.eds["letters"]) == 0
    templates = [c.request.url.params.get_list("template") for c in fb.eds["approvals"].calls]
    assert ["memo", "application", "report"] not in templates


async def test_counters_and_cards_count_only_own_steps(web: Web, fb: FeedBackends) -> None:
    fb.state["memos"] = page(route("СЗ-2026/031"), {**route("СЗ-2026/032"), "acting_for": MADINA})
    fb.state["covering"] = [
        {
            "user_id": 12,
            "full_name": "Мадина Р.",
            "date_from": "2027-01-10",
            "date_to": "2027-01-20",
        }
    ]
    await web.login(["DIRECTOR"])

    items = (await web.client.get("/api/v1/queue")).json()["items"]
    cards = (await web.client.get("/api/v1/queue/cards")).json()["cards"]
    counters = (await web.client.get("/api/v1/menu-counters")).json()["items"]

    assert len([i for i in items if i["kind"] == "approve_memo"]) == 2
    assert {c["key"]: c["count"] for c in cards}["memos_to_approve"] == 1
    badge = next(c for c in counters if c["module"] == "eds" and c["section"] == "approvals")
    assert badge["count"] == 1
    tasks_badge = next(
        c for c in counters if c["module"] == "dashboard" and c["section"] == "queue"
    )
    # бейдж «Задачи» — число строк списка, в том числе «за …»; бейдж «Согласования» — только свои
    assert tasks_badge["count"] == 2
