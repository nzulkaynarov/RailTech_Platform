"""EDS · Поручения по входящим (P8b, SPEC-v3 §3.2a; контракт BFF 0.31.0).

EDS — на respx (`eds_letters_support`), ответы BFF проверяются по схемам platform-bff.yaml.
Проверяется то, что делает BFF: путь резолюции из EDS (и запасное правило для старого EDS),
карточка с проектом, резолюцией делопроизводства, поручениями, переносами и ознакомлением; тела
запросов EDS (id сотрудников числом); разделы каталога до EDS (проект — делопроизводитель или
директор, резолюция и решение переноса — директор); операции исполнителя — любому вошедшему, решает
EDS; список сотрудников и фильтры журнала. Решения (исполнитель, срочные не продлеваются) — в EDS.
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import (
    FILE_ID,
    LETTER_ID,
    NUMBER,
    EdsFake,
    eds_error_body,
    letter,
    person,
    row,
)
from tests.roles import Role

BASE = "/api/v1/eds"
CARD = f"{BASE}/letters/{LETTER_ID}"
INSTRUCTION_ID = "50000000-0000-4000-8000-000000000001"
EXTENSION_ID = "60000000-0000-4000-8000-000000000001"
OUT_ID = "70000000-0000-4000-8000-000000000014"


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    return EdsFake(be)


def office_letter(**over: Any) -> dict[str, Any]:
    """Требование ГНК на исполнении: поручение с отчётом и историей переносов, ознакомление."""
    return letter(
        number="ВХ-112/26",
        status="in_execution",
        subject="Требование ГНК о пояснениях",
        kind="tax_notice",
        receipt_method="taxpayer_cabinet",
        links={
            "erp_request_id": None,
            "erp_deal_id": None,
            "deal_number": None,
            "crm_client_id": None,
            "erp_company_id": None,
        },
        track="office",
        on_control=True,
        suggested_due="2026-11-04",
        resolution_draft=None,
        office_resolution={
            "kind": "execute",
            "text": "Подготовить пояснения и приложить расчёт.",
            "due": "2026-11-05",
            "responsible": person(7, "Иван Исполнитель"),
            "co_executors": [],
            "acquaint": [person(9, "Ольга Бухгалтер")],
            "decided_by": person(1, "Директор Демо"),
            "decided_at": "2026-11-01T08:00:00Z",
        },
        instructions=[
            {
                "id": INSTRUCTION_ID,
                "kind": "execute",
                "role": "responsible",
                "person": person(7, "Иван Исполнитель"),
                "due": "2026-11-05",
                "text": "Подготовить пояснения и приложить расчёт.",
                "status": "executed",
                "overdue": False,
                "report": "Пояснения отправлены.",
                "files": [
                    {
                        "id": FILE_ID,
                        "name": "отчёт.pdf",
                        "content_type": "application/pdf",
                        "size": 1024,
                        "version": 1,
                        "sha256": "b" * 64,
                        "uploaded_at": "2026-11-03T10:00:00Z",
                        "uploaded_by": person(7, "Иван Исполнитель"),
                    }
                ],
                "outgoing": {"id": OUT_ID, "number": "ИСХ-014/26"},
                "executed_at": "2026-11-03T10:05:00Z",
                "extensions": [
                    {
                        "id": EXTENSION_ID,
                        "old_due": "2026-11-05",
                        "new_due": "2026-11-10",
                        "reason": "Ждём выписку банка.",
                        "status": "rejected",
                        "requested_by": person(7, "Иван Исполнитель"),
                        "requested_at": "2026-11-02T09:00:00Z",
                        "decided_by": person(1, "Директор Демо"),
                        "decided_at": "2026-11-02T10:00:00Z",
                        "comment": "Срок ГНК не переносится.",
                    }
                ],
            }
        ],
        acquaintances=[
            {"person": person(9, "Ольга Бухгалтер"), "acknowledged_at": None},
        ],
        executed_at=None,
        **over,
    )


def _serve(eds: EdsFake, body: dict[str, Any]) -> None:
    eds.letters[LETTER_ID] = body


# --- карточка и путь -----------------------------------------------------------------------------


async def test_card_shows_office_resolution_instructions_and_acquaintances(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    _serve(eds, office_letter())
    assert (await web.login(["DIRECTOR"])).status_code == 200

    response = await web.client.get(CARD)

    check(response, "/eds/letters/{ref}", "get")
    body = response.json()
    assert (body["track"], body["status"], body["on_control"]) == ("office", "in_execution", True)
    assert body["suggested_due"] == "2026-11-04"
    assert body["stage"] == "RESOLUTION"
    assert body["request"] is None
    resolution = body["office_resolution"]
    assert resolution["responsible"] == {"id": "7", "name": "Иван Исполнитель", "initials": "ИИ"}
    assert [p["id"] for p in resolution["acquaint"]] == ["9"]
    [instruction] = body["instructions"]
    assert instruction["outgoing"] == {
        "number": "ИСХ-014/26",
        "path": f"/eds/documents?scope=all&doc={OUT_ID}&panel=open",
    }
    assert instruction["files"][0]["name"] == "отчёт.pdf"
    assert instruction["extensions"][0]["status"] == "rejected"
    assert instruction["extensions"][0]["decided_by"]["id"] == "1"
    assert body["acquaintances"] == [
        {
            "person": {"id": "9", "name": "Ольга Бухгалтер", "initials": "ОБ"},
            "acknowledged_at": None,
        }
    ]


async def test_old_eds_without_track_gets_the_track_by_the_rule(web: Web, eds: EdsFake) -> None:
    """Письмо по заявке (`erp_request_id`) — «расчёт»; с видом документа без заявки —
    делопроизводство; списки поручений пустые."""
    assert (await web.login(["DIRECTOR"])).status_code == 200
    body = (await web.client.get(CARD)).json()
    assert (body["track"], body["instructions"], body["acquaintances"]) == ("calc", [], [])

    _serve(eds, {**office_letter(), "track": None})
    del eds.letters[LETTER_ID]["track"]
    body = (await web.client.get(CARD)).json()
    assert body["track"] == "office"


@pytest.mark.parametrize("roles", [["ADMIN"], ["SUPPLY"]])
async def test_executor_without_the_inbox_section_reaches_eds_for_the_card_and_files(
    web: Web, eds: EdsFake, roles: list[Role]
) -> None:
    """Исполнитель видит письмо своего поручения без `eds.inbox` — решает EDS (§3.2a «Права»)."""
    _serve(eds, office_letter())
    assert (await web.login(roles)).status_code == 200

    assert (await web.client.get(CARD)).status_code == 200
    assert (await web.client.get(f"{BASE}/letter-files/{FILE_ID}")).status_code == 200

    eds.answer(
        "GET",
        f"letters/{LETTER_ID}",
        httpx.Response(
            403,
            json=eds_error_body("FORBIDDEN", "Нет доступа.", permission="letters.read"),
        ),
    )
    denied = await web.client.get(CARD)
    assert denied.status_code == 403
    assert denied.json()["source"] == "eds"


# --- проект и резолюция делопроизводства ----------------------------------------------------


async def test_registrar_saves_a_draft_with_ids_as_numbers(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    eds.answer("PUT", f"letters/{LETTER_ID}/resolution-draft", httpx.Response(200, json=letter()))
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.send(
        "PUT",
        f"{CARD}/resolution-draft",
        json={
            "kind": "reply",
            "responsible_id": "7",
            "due": "2026-11-05",
            "text": "  Подготовить ответ.  ",
            "co_executor_ids": ["8", "8"],
            "acquaint_ids": [],
        },
    )

    assert response.status_code == 200
    check(response, "/eds/letters/{id}/resolution-draft", "put")
    [call] = eds.made("PUT", f"letters/{LETTER_ID}/resolution-draft")
    assert json.loads(call.content) == {
        "kind": "reply",
        "responsible_crm_user_id": 7,
        "due": "2026-11-05",
        "text": "Подготовить ответ.",
        "co_executor_ids": [8],
        "acquaint_ids": [],
    }


async def test_director_resolves_an_office_letter(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    eds.answer(
        "POST",
        f"letters/{LETTER_ID}/office-resolution",
        httpx.Response(200, json=office_letter()),
    )
    assert (await web.login(["DIRECTOR"])).status_code == 200

    response = await web.send(
        "POST",
        f"{CARD}/office-resolution",
        json={
            "kind": "execute",
            "responsible_id": "7",
            "due": "2026-11-05",
            "text": "Подготовить пояснения.",
            "acquaint_ids": ["9"],
        },
    )

    assert response.status_code == 200
    check(response, "/eds/letters/{id}/office-resolution", "post")
    [call] = eds.made("POST", f"letters/{LETTER_ID}/office-resolution")
    assert json.loads(call.content) == {
        "kind": "execute",
        "responsible_crm_user_id": 7,
        "due": "2026-11-05",
        "text": "Подготовить пояснения.",
        "co_executor_ids": [],
        "acquaint_ids": [9],
    }


async def test_resolution_and_draft_need_their_sections_before_eds(web: Web, eds: EdsFake) -> None:
    """Делопроизводитель — только проект; менеджер-читатель — ни проекта, ни резолюции."""
    assert (await web.login(["REGISTRAR"])).status_code == 200
    resolve = await web.send(
        "POST", f"{CARD}/office-resolution", json={"kind": "info", "text": "К сведению."}
    )
    assert resolve.status_code == 403
    decide = await web.send(
        "POST",
        f"{BASE}/instructions/{INSTRUCTION_ID}/extension/decision",
        json={"decision": "approve"},
    )
    assert decide.status_code == 403

    assert (await web.login(["MANAGER"])).status_code == 200
    draft = await web.send("PUT", f"{CARD}/resolution-draft", json={"kind": None})
    assert draft.status_code == 403
    assert (await web.client.get(f"{BASE}/staff")).status_code == 403
    assert [c for c in eds.calls if "exchange" not in c.url.path] == []


async def test_track_mismatch_from_eds_is_a_conflict(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "POST",
        f"letters/{LETTER_ID}/office-resolution",
        httpx.Response(
            409,
            json=eds_error_body(
                "CONFLICT", "Письмо по заявке — резолюция «расчёт».", reason="track_mismatch"
            ),
        ),
    )
    assert (await web.login(["DIRECTOR"])).status_code == 200

    response = await web.send(
        "POST",
        f"{CARD}/office-resolution",
        json={"kind": "reply", "responsible_id": "7", "due": "2026-11-05", "text": "Ответить."},
    )

    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "track_mismatch"


# --- исполнитель и автор резолюции -------------------------------------------------------------


async def test_any_employee_completes_and_asks_for_an_extension_eds_decides(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    path = f"instructions/{INSTRUCTION_ID}"
    eds.answer("POST", f"{path}/complete", httpx.Response(200, json=office_letter()))
    eds.answer("POST", f"{path}/extension", httpx.Response(200, json=office_letter()))
    assert (await web.login(["SUPPLY"])).status_code == 200

    done = await web.send(
        "POST",
        f"{BASE}/{path}/complete",
        json={"report": " Готово. ", "file_ids": [FILE_ID], "outgoing_number": "ИСХ-014/26"},
    )
    assert done.status_code == 200
    check(done, "/eds/instructions/{id}/complete", "post")
    assert json.loads(eds.made("POST", f"{path}/complete")[0].content) == {
        "report": "Готово.",
        "file_ids": [FILE_ID],
        "outgoing_number": "ИСХ-014/26",
    }

    asked = await web.send(
        "POST",
        f"{BASE}/{path}/extension",
        json={"new_due": "2026-11-10", "reason": "Ждём выписку банка."},
    )
    assert asked.status_code == 200
    check(asked, "/eds/instructions/{id}/extension", "post")
    assert json.loads(eds.made("POST", f"{path}/extension")[0].content) == {
        "new_due": "2026-11-10",
        "reason": "Ждём выписку банка.",
    }


async def test_eds_refusals_of_the_executor_are_passed_through(web: Web, eds: EdsFake) -> None:
    path = f"instructions/{INSTRUCTION_ID}"
    eds.answer(
        "POST",
        f"{path}/complete",
        httpx.Response(
            403, json=eds_error_body("FORBIDDEN", "Чужое поручение.", reason="not_executor")
        ),
    )
    eds.answer(
        "POST",
        f"{path}/extension",
        httpx.Response(
            409,
            json=eds_error_body(
                "CONFLICT", "Срочное поручение не продлевается.", reason="urgent_not_extendable"
            ),
        ),
    )
    assert (await web.login(["MANAGER"])).status_code == 200

    denied = await web.send("POST", f"{BASE}/{path}/complete", json={"report": "x"})
    assert (denied.status_code, denied.json()["details"]["reason"]) == (403, "not_executor")
    urgent = await web.send(
        "POST", f"{BASE}/{path}/extension", json={"new_due": "2026-11-10", "reason": "x"}
    )
    assert urgent.status_code == 409
    assert urgent.json()["details"]["reason"] == "urgent_not_extendable"
    assert urgent.json()["message"] == "Срочное поручение не продлевается."


async def test_director_decides_the_extension_and_the_employee_acknowledges(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    decision = f"instructions/{INSTRUCTION_ID}/extension/decision"
    eds.answer("POST", decision, httpx.Response(200, json=office_letter()))
    eds.answer("POST", f"letters/{LETTER_ID}/acquaint", httpx.Response(200, json=office_letter()))
    assert (await web.login(["DIRECTOR"])).status_code == 200

    decided = await web.send(
        "POST", f"{BASE}/{decision}", json={"decision": "reject", "comment": "  "}
    )
    assert decided.status_code == 200
    check(decided, "/eds/instructions/{id}/extension/decision", "post")
    assert json.loads(eds.made("POST", decision)[0].content) == {
        "decision": "reject",
        "comment": None,
    }

    assert (await web.login(["ACCOUNTANT"])).status_code == 200
    seen = await web.send("POST", f"{CARD}/acquaint")
    assert seen.status_code == 200
    check(seen, "/eds/letters/{id}/acquaint", "post")


# --- сотрудники, журнал, регистрация -----------------------------------------------------------


async def test_staff_list_is_sorted_and_mapped(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    eds.answer(
        "GET",
        "employees",
        httpx.Response(
            200,
            json={
                "items": [
                    {"crm_user_id": 7, "full_name": "Иван Исполнитель", "position": None},
                    {"crm_user_id": 1, "full_name": "Директор Демо", "position": "Директор"},
                ]
            },
        ),
    )
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.client.get(f"{BASE}/staff")

    check(response, "/eds/staff", "get")
    assert response.json() == {
        "items": [
            {"id": "1", "name": "Директор Демо", "position": "Директор"},
            {"id": "7", "name": "Иван Исполнитель", "position": None},
        ]
    }


async def test_journal_filters_and_columns(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    eds.page = {
        "items": [
            row(
                kind="tax_notice",
                track="office",
                status="in_execution",
                due="2026-11-05",
                on_control=True,
                overdue=True,
                executor=person(7, "Иван Исполнитель"),
            )
        ],
        "next_cursor": None,
    }
    assert (await web.login(["DIRECTOR"])).status_code == 200

    response = await web.client.get(
        f"{BASE}/letters", params={"on_control": "true", "overdue": "true"}
    )

    check(response, "/eds/letters", "get")
    [item] = response.json()["items"]
    assert (item["track"], item["on_control"], item["overdue"]) == ("office", True, True)
    assert item["executor"]["id"] == "7"
    [call] = eds.made("GET", "letters")
    assert (call.url.params["on_control"], call.url.params["overdue"]) == ("true", "true")


async def test_registration_passes_the_addressee_and_the_draft(web: Web, eds: EdsFake) -> None:
    eds.answer("POST", "letters", httpx.Response(201, json=letter(number=NUMBER)))
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.send(
        "POST",
        f"{BASE}/letters",
        json={
            "kind": "tax_notice",
            "receipt_method": "taxpayer_cabinet",
            "sender_name": "ГНК Мирабадского района",
            "received_at": "2026-11-01",
            "subject": "Требование о пояснениях",
            "file_ids": [FILE_ID],
            "addressee_id": "1",
            "resolution_draft": {"kind": "execute", "responsible_id": "7", "due": "2026-11-04"},
        },
    )

    assert response.status_code == 201
    body = json.loads(eds.made("POST", "letters")[0].content)
    assert body["addressee_crm_user_id"] == 1
    assert body["resolution_draft"] == {
        "kind": "execute",
        "responsible_crm_user_id": 7,
        "due": "2026-11-04",
        "text": None,
        "co_executor_ids": [],
        "acquaint_ids": [],
    }
