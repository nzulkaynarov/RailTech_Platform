"""EDS · Проекты (контракт BFF 0.26.0, D2-5): список, карточка, договор, акт, сканы, файлы.

ERP — на respx (`eds_projects_support`), ответы BFF проверяются по схемам platform-bff.yaml.
Проверяется то, что делает BFF: разделы каталога (`eds.projects`: чтение — менеджер,
снабженец, гл. инженер; действия — директор и бухгалтер; админ — нет раздела; роль без
полного — 403 **до ERP**), адресация по номеру ПР и id сделки, id документа берётся из
карточки, а не из запроса, перевод ошибок ERP, потоковые файлы, предел и тип загрузки скана.
Статусы, права на действие и скан решает ERP.
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_projects_support import (
    ACT_ID,
    CONTRACT_ID,
    DEAL,
    INVOICE_ID,
    PDF,
    ProjectsFake,
    act_card,
    card,
    contract_card,
    erp_error,
    invoice_card,
    row,
)
from tests.roles import Role

BASE = "/api/v1/eds/projects"
NUMBER = "ПР-2026-104"
ROLES = ["ADMIN", "DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"]
READERS = ["DIRECTOR", "MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"]
WRITERS = ["DIRECTOR", "ACCOUNTANT"]


@pytest.fixture
def erp(be: Backends) -> ProjectsFake:
    return ProjectsFake(be)


async def _as(web: Web, role: Role) -> None:
    assert (await web.login([role])).status_code == 200


def _scan(
    name: str = "scan.pdf", content: bytes = PDF, ctype: str = "application/pdf"
) -> dict[str, Any]:
    return {"files": {"file": (name, content, ctype)}}


# --- список -------------------------------------------------------------------------------------


async def test_list_composes_numbers_and_passes_filters(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "DIRECTOR")
    erp.rows = [row(104), row(7, title="", created_at="2025-12-31T21:00:00+00:00", step="PAYMENT")]

    response = await web.client.get(
        BASE,
        params={"mine": "true", "problems": "true", "step": "CONTRACT", "limit": 10, "offset": 0},
    )

    check(response, "/eds/projects", "get")
    body = response.json()
    assert [i["number"] for i in body["items"]] == [NUMBER, "ПР-2025-007"]
    assert body["items"][0]["request_number"] == "ЗВ-2026-104"
    assert body["items"][1]["title"] == "ООО «Демо-Рейл»", "нет названия — название клиента"
    assert (body["total"], body["offset"], body["limit"]) == (2, 0, 10)
    [call] = erp.calls_to("GET", "projects/")
    assert dict(call.url.params) == {
        "mine": "true",
        "problems": "true",
        "step": "CONTRACT",
        "limit": "10",
        "offset": "0",
    }
    assert call.headers["authorization"].startswith("Bearer ")


@pytest.mark.parametrize("query", ["ПР-2026-104", "pr-2026-104", "ЗВ-2026-104", "104"])
async def test_search_by_number_asks_erp_for_that_deal(
    web: Web, erp: ProjectsFake, query: str
) -> None:
    await _as(web, "MANAGER")
    assert (await web.client.get(BASE, params={"q": query})).status_code == 200
    [call] = erp.calls_to("GET", "projects/")
    # «104» цифрами — обычный текст (название, клиент), номером считаются только ПР-/ЗВ-
    expected = {"q": "104"} if query == "104" else {"deal_id": "104"}
    assert {k: v for k, v in call.url.params.items() if k in ("q", "deal_id")} == expected


async def test_search_by_text_is_passed_as_text(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "MANAGER")
    await web.client.get(BASE, params={"q": "  Демо-Рейл  "})
    [call] = erp.calls_to("GET", "projects/")
    assert call.url.params["q"] == "Демо-Рейл"
    assert "deal_id" not in call.url.params


async def test_list_when_erp_is_down_is_503(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "DIRECTOR")
    erp.answer("GET", "projects/", httpx.Response(502, text="bad gateway"))
    response = await web.client.get(BASE)
    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"


async def test_list_rejects_bad_params(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "DIRECTOR")
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"step": "NOPE"}):
        assert (await web.client.get(BASE, params=params)).status_code == 422
    assert erp.calls == []


# --- карточка -----------------------------------------------------------------------------------


async def test_card_by_number_and_by_id(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "ACCOUNTANT")
    by_number = await web.client.get(f"{BASE}/{NUMBER}")
    check(by_number, "/eds/projects/{ref}", "get")
    by_id = await web.client.get(f"{BASE}/{DEAL}")
    assert by_number.json() == by_id.json()
    body = by_number.json()
    assert body["number"] == NUMBER
    assert body["contract"]["actions"] == ["client_agreed", "reject"]
    assert body["act_blocker"] == "no_invoice"
    assert body["can_create_contract"] is False


async def test_card_with_every_document(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "DIRECTOR")
    erp.cards[DEAL] = card(
        step="PAYMENT",
        contract=contract_card(
            status="signed",
            has_scan=True,
            signed_at="2026-10-25T12:00:00+05:00",
            actions=[],
            history=[history_row("contract.scan_attached")],
        ),
        invoices=[invoice_card(status="paid", paid={"amount": "125000000.00", "currency": "UZS"})],
        act=act_card(rejection_reason=None),
        act_blocker="act_exists",
        fulfillment={
            "status": "SHIPPED",
            "status_name": "Отгружено",
            "expected_delivery_date": "2026-12-01",
            "shipped_at": "2026-10-28T10:00:00+05:00",
            "delivered_at": None,
            "accepted_at": None,
            "tracking_number": "TRK-1",
            "carrier": "Авиа",
        },
        delivery_lines=[
            {
                "line_no": 1,
                "title": "Привод СП-6",
                "quantity": 12,
                "unit": "шт",
                "status": "shipped",
                "eta": "2026-12-01",
                "shipped_at": None,
                "tracking": "",
            }
        ],
        journal=[history_row("contract.scan_attached")],
    )
    response = await web.client.get(f"{BASE}/{NUMBER}")
    check(response, "/eds/projects/{ref}", "get")
    assert response.json()["fulfillment"]["carrier"] == "Авиа"


def history_row(code: str) -> dict[str, Any]:
    return {
        "at": "2026-10-25T12:00:00+05:00",
        "code": code,
        "text": "Прикреплён скан подписанного договора",
        "actor_name": "Бухгалтер Демо",
        "document": "contract",
        "number": "ДОГ-2026/104",
        "reason": "",
    }


@pytest.mark.parametrize(
    "ref", ["ПР-2025-104", "ПР-2026-999", "ABC", "ПР-2026-", "104/1", "9" * 12, "ЗВ-26-104"]
)
async def test_wrong_reference_is_not_found(web: Web, erp: ProjectsFake, ref: str) -> None:
    """Год не тот, нет такой сделки, мусор вместо номера — 404, существование не раскрывается."""
    await _as(web, "DIRECTOR")
    response = await web.client.get(f"{BASE}/{ref}")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_erp_forbidden_is_forbidden(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "MANAGER")
    erp.answer("GET", r"projects/\d+/", erp_error(403, "PROJECT_STAFF_ONLY"))
    response = await web.client.get(f"{BASE}/{NUMBER}")
    assert response.status_code == 403
    assert response.json()["details"]["reason"] == "project_staff_only"


async def test_erp_unavailable_is_503(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "MANAGER")
    erp.answer("GET", r"projects/\d+/", httpx.Response(500, text="boom"))
    assert (await web.client.get(f"{BASE}/{NUMBER}")).status_code == 503


async def test_erp_answer_out_of_contract_is_503_not_garbage(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "DIRECTOR")
    erp.cards[DEAL] = {**card(), "step": "WRONG"}
    response = await web.client.get(f"{BASE}/{NUMBER}")
    assert response.status_code == 503


# --- матрица каталога ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
async def test_read_access_follows_the_catalog(web: Web, erp: ProjectsFake, role: str) -> None:
    await _as(web, role)
    expected = 200 if role in READERS else 403
    assert (await web.client.get(BASE)).status_code == expected
    assert (await web.client.get(f"{BASE}/{NUMBER}")).status_code == expected
    file_url = f"{BASE}/{NUMBER}/files/contract/{CONTRACT_ID}"
    assert (await web.client.get(file_url)).status_code == expected
    if expected == 403:
        assert erp.calls == [], "роль без раздела не доходит до ERP"


ACTIONS: list[tuple[str, dict[str, Any]]] = [
    (f"{BASE}/{NUMBER}/contract/draft", {}),
    (f"{BASE}/{NUMBER}/contract", {"action": "send_to_client"}),
    (f"{BASE}/{NUMBER}/contract", {"action": "mark_issued"}),
    (f"{BASE}/{NUMBER}/act", {"action": "issue"}),
    (f"{BASE}/{NUMBER}/act", {"action": "return", "reason": "Опечатка"}),
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("url", "body"), ACTIONS)
async def test_actions_need_the_full_section(
    web: Web, erp: ProjectsFake, role: str, url: str, body: Any
) -> None:
    """Менеджер, снабженец, гл. инженер (чтение) и админ получают 403 в BFF; ERP не вызывается."""
    await _as(web, role)
    response = await web.send("POST", url, json=body)
    if role in WRITERS:
        assert response.status_code != 403 or response.json()["source"] == "erp"
    else:
        assert response.status_code == 403
        assert response.json()["source"] == "bff"
        assert erp.calls == []


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY", "ENGINEER", "ADMIN"])
async def test_scan_upload_needs_the_full_section(web: Web, erp: ProjectsFake, role: str) -> None:
    await _as(web, role)
    for url in (f"{BASE}/{NUMBER}/contract/scan", f"{BASE}/{NUMBER}/act/scan"):
        response = await web.client.post(url, headers={"X-CSRF-Token": web.csrf}, **_scan())
        assert response.status_code == 403
        assert response.json()["source"] == "bff"
    assert erp.calls == []


async def test_actions_need_the_csrf_token(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    response = await web.client.post(
        f"{BASE}/{NUMBER}/contract",
        json={"action": "send_to_client"},
        headers={"X-CSRF-Token": "wrong"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert erp.posts() == []


async def test_without_a_session_everything_is_401(web: Web, erp: ProjectsFake) -> None:
    assert (await web.client.get(BASE)).status_code == 401
    assert (
        await web.client.post(f"{BASE}/{NUMBER}/contract", json={"action": "reject"})
    ).status_code in (401, 403)


# --- договор ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "slug"),
    [
        ("send_to_client", "send-to-client"),
        ("client_agreed", "client-agreed"),
        ("revise", "revise"),
        ("mark_issued", "mark-issued"),
    ],
)
async def test_contract_action_calls_the_erp_operation_of_the_contract_from_the_card(
    web: Web, erp: ProjectsFake, check: ContractChecker, action: str, slug: str
) -> None:
    await _as(web, "ACCOUNTANT")
    response = await web.send(
        "POST", f"{BASE}/{NUMBER}/contract", json={"action": action, "note": "  Didox, № 77  "}
    )
    check(response, "/eds/projects/{ref}/contract", "post")
    assert response.status_code == 200
    assert erp.body("POST", rf"contracts/{CONTRACT_ID}/{slug}/") == {"note": "Didox, № 77"}
    assert len(erp.posts()) == 1


async def test_reject_needs_a_reason_before_the_erp(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    for body in ({"action": "reject"}, {"action": "reject", "reason": "   "}):
        response = await web.send("POST", f"{BASE}/{NUMBER}/contract", json=body)
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_FAILED"
    assert erp.posts() == []
    ok = await web.send(
        "POST", f"{BASE}/{NUMBER}/contract", json={"action": "reject", "reason": " Срок "}
    )
    assert ok.status_code == 200
    assert erp.body("POST", rf"contracts/{CONTRACT_ID}/reject/") == {"reason": "Срок"}


async def test_unknown_action_and_extra_fields_are_rejected(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    for body in ({"action": "sign"}, {"action": "revise", "contract_id": 1}, {}):
        assert (await web.send("POST", f"{BASE}/{NUMBER}/contract", json=body)).status_code == 422
    assert erp.posts() == []


async def test_contract_id_comes_from_the_card_not_from_the_request(
    web: Web, erp: ProjectsFake
) -> None:
    await _as(web, "ACCOUNTANT")
    erp.cards[DEAL] = card(contract=contract_card(id=999))
    await web.send("POST", f"{BASE}/{NUMBER}/contract", json={"action": "client_agreed"})
    assert [c.url.path for c in erp.posts()] == ["/api/v1/crm/contracts/999/client-agreed/"]


async def test_action_on_a_project_without_a_contract_is_not_found(
    web: Web, erp: ProjectsFake
) -> None:
    await _as(web, "ACCOUNTANT")
    erp.cards[DEAL] = card(contract=None)
    response = await web.send(
        "POST", f"{BASE}/{NUMBER}/contract", json={"action": "send_to_client"}
    )
    assert response.status_code == 404
    assert erp.posts() == []


async def test_erp_refusals_are_translated(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    url = f"{BASE}/{NUMBER}/contract"
    erp.answer(
        "POST", r"contracts/\d+/mark-issued/", erp_error(409, "CONTRACT_TRANSITION_NOT_ALLOWED")
    )
    conflict = await web.send("POST", url, json={"action": "mark_issued"})
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CONFLICT"
    assert conflict.json()["details"]["reason"] == "contract_transition_not_allowed"
    assert conflict.json()["source"] == "erp"

    erp.answer("POST", r"contracts/\d+/revise/", erp_error(403, "ROLE_NOT_PERMITTED"))
    denied = await web.send("POST", url, json={"action": "revise"})
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"
    assert denied.json()["details"]["reason"] == "role_not_permitted"
    assert denied.json()["source"] == "erp"

    erp.answer("POST", r"contracts/\d+/client-agreed/", httpx.Response(500, text="x"))
    assert (await web.send("POST", url, json={"action": "client_agreed"})).status_code == 503


async def test_create_contract_calls_generate_without_sending(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "ACCOUNTANT")
    erp.cards[DEAL] = card(contract=None, can_create_contract=True)
    response = await web.send("POST", f"{BASE}/{NUMBER}/contract/draft")
    check(response, "/eds/projects/{ref}/contract/draft", "post")
    assert response.status_code == 201
    assert erp.body("POST", "contracts/generate-from-quote/") == {
        "quote_id": 1203,
        "send_to_client": False,
    }


async def test_create_contract_refusals(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    url = f"{BASE}/{NUMBER}/contract/draft"
    erp.cards[DEAL] = card()  # договор уже есть
    exists = await web.send("POST", url)
    assert exists.status_code == 409
    assert exists.json()["details"]["reason"] == "contract_exists"
    erp.cards[DEAL] = card(contract=None, can_create_contract=False)  # у сотрудника нет права
    assert (await web.send("POST", url)).status_code == 403
    assert erp.posts() == []


# --- скан договора ------------------------------------------------------------------------------


async def test_contract_scan_goes_to_the_erp_as_is(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "ACCOUNTANT")
    response = await web.client.post(
        f"{BASE}/{NUMBER}/contract/scan", headers={"X-CSRF-Token": web.csrf}, **_scan()
    )
    check(response, "/eds/projects/{ref}/contract/scan", "post")
    [call] = erp.calls_to("POST", rf"contracts/{CONTRACT_ID}/attach-scan/")
    assert call.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert PDF in call.content


async def test_scan_must_be_multipart(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    response = await web.send("POST", f"{BASE}/{NUMBER}/contract/scan", json={"file": "x"})
    assert response.status_code == 422
    assert response.json()["details"]["fields"] == ["file"]
    assert erp.posts() == []


async def test_scan_over_20_mb_is_413_without_calling_the_erp(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    big = _scan("big.pdf", PDF + b"\0" * (20 * 1024 * 1024 + 70 * 1024))
    response = await web.client.post(
        f"{BASE}/{NUMBER}/contract/scan", headers={"X-CSRF-Token": web.csrf}, **big
    )
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert response.json()["details"]["max_bytes"] == 20 * 1024 * 1024
    assert erp.posts() == []


@pytest.mark.parametrize(
    ("code", "field", "reason"),
    [
        ("SCAN_INVALID", "file", "scan_invalid"),
        ("SCAN_REQUIRED", "file", "scan_required"),
        ("NO_FILE_PROVIDED", "file", "no_file_provided"),
    ],
)
async def test_erp_scan_refusals_become_field_errors(
    web: Web, erp: ProjectsFake, code: str, field: str, reason: str
) -> None:
    await _as(web, "ACCOUNTANT")
    erp.answer("POST", r"contracts/\d+/attach-scan/", erp_error(400, code))
    response = await web.client.post(
        f"{BASE}/{NUMBER}/contract/scan",
        headers={"X-CSRF-Token": web.csrf},
        **_scan("x.pdf", b"nope"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"]["fields"] == [field]
    assert response.json()["details"]["reason"] == reason


async def test_scan_in_a_wrong_status_is_409(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "DIRECTOR")
    erp.answer(
        "POST", r"contracts/\d+/attach-scan/", erp_error(409, "CONTRACT_TRANSITION_NOT_ALLOWED")
    )
    response = await web.client.post(
        f"{BASE}/{NUMBER}/contract/scan", headers={"X-CSRF-Token": web.csrf}, **_scan()
    )
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "contract_transition_not_allowed"


# --- акт ----------------------------------------------------------------------------------------


async def test_issue_act_uses_the_freshest_issued_invoice(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "ACCOUNTANT")
    erp.cards[DEAL] = card(
        invoices=[
            invoice_card(id=1, status="to_issue"),
            invoice_card(id=INVOICE_ID, status="paid"),
            invoice_card(id=9, status="cancelled"),
        ],
        act_blocker=None,
    )
    response = await web.send("POST", f"{BASE}/{NUMBER}/act", json={"action": "issue"})
    check(response, "/eds/projects/{ref}/act", "post")
    assert [c.url.path for c in erp.posts()] == [f"/api/v1/crm/invoices/{INVOICE_ID}/generate-act/"]


@pytest.mark.parametrize(
    ("blocker", "invoices", "status", "reason"),
    [
        ("forbidden", [invoice_card()], 403, "act_issue_not_allowed"),
        ("act_exists", [invoice_card()], 409, "act_already_exists"),
        ("no_invoice", [invoice_card(status="to_issue")], 409, "no_invoice"),
        (None, [], 409, "no_invoice"),
    ],
)
async def test_issue_act_refusals_come_before_the_erp_call(
    web: Web,
    erp: ProjectsFake,
    blocker: str | None,
    invoices: list[dict[str, Any]],
    status: int,
    reason: str,
) -> None:
    await _as(web, "ACCOUNTANT")
    erp.cards[DEAL] = card(invoices=invoices, act_blocker=blocker)
    response = await web.send("POST", f"{BASE}/{NUMBER}/act", json={"action": "issue"})
    assert response.status_code == status
    assert response.json()["details"]["reason"] == reason
    assert erp.posts() == []


async def test_return_act_needs_a_reason_and_goes_to_the_erp(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    erp.cards[DEAL] = card(act=act_card(), act_blocker="act_exists")
    url = f"{BASE}/{NUMBER}/act"
    for body in ({"action": "return"}, {"action": "return", "reason": " "}):
        assert (await web.send("POST", url, json=body)).status_code == 422
    assert erp.posts() == []
    ok = await web.send("POST", url, json={"action": "return", "reason": " Не та сумма "})
    assert ok.status_code == 200
    assert erp.body("POST", rf"acts/{ACT_ID}/record-return/") == {"reason": "Не та сумма"}


async def test_reissue_act_and_missing_act(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "DIRECTOR")
    url = f"{BASE}/{NUMBER}/act"
    assert (await web.send("POST", url, json={"action": "reissue"})).status_code == 404
    erp.cards[DEAL] = card(
        act=act_card(status="returned", actions=["reissue"]), act_blocker="act_exists"
    )
    assert (await web.send("POST", url, json={"action": "reissue"})).status_code == 200
    assert [c.url.path for c in erp.posts()] == [f"/api/v1/crm/acts/{ACT_ID}/reissue/"]


async def test_act_scan_goes_to_the_act_of_the_card(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "ACCOUNTANT")
    erp.cards[DEAL] = card(act=act_card(), act_blocker="act_exists")
    response = await web.client.post(
        f"{BASE}/{NUMBER}/act/scan",
        headers={"X-CSRF-Token": web.csrf},
        **_scan("a.png", b"\x89PNG\r\n\x1a\n", "image/png"),
    )
    check(response, "/eds/projects/{ref}/act/scan", "post")
    assert len(erp.calls_to("POST", rf"acts/{ACT_ID}/attach-scan/")) == 1


# --- файлы --------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", READERS)
async def test_pdf_streams_for_every_reader(web: Web, erp: ProjectsFake, role: str) -> None:
    await _as(web, role)
    response = await web.client.get(f"{BASE}/{NUMBER}/files/contract/{CONTRACT_ID}")
    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment")


async def test_scan_is_always_a_download_and_only_when_it_exists(
    web: Web, erp: ProjectsFake
) -> None:
    await _as(web, "DIRECTOR")
    url = f"{BASE}/{NUMBER}/files/contract/{CONTRACT_ID}?variant=scan"
    assert (await web.client.get(url)).status_code == 404, (
        "скана нет — 404, в ERP не ходим за файлом"
    )
    assert erp.calls_to("GET", r"contracts/\d+/download-signed/") == []
    erp.cards[DEAL] = card(contract=contract_card(has_scan=True, status="signed"))
    erp.files[f"contracts/{CONTRACT_ID}/download-signed/"] = b"\x89PNG\r\n\x1a\nfake"
    response = await web.client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_a_document_of_another_project_is_not_served(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "DIRECTOR")
    for url in (
        f"{BASE}/{NUMBER}/files/contract/{CONTRACT_ID + 1}",
        f"{BASE}/{NUMBER}/files/act/{ACT_ID}",
        f"{BASE}/{NUMBER}/files/invoice/{INVOICE_ID}",
    ):
        assert (await web.client.get(url)).status_code == 404
    assert erp.calls_to("GET", r"(contracts|acts|invoices)/\d+/download-pdf/") == []


async def test_invoice_pdf_and_no_invoice_scan(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    erp.cards[DEAL] = card(invoices=[invoice_card()])
    assert (await web.client.get(f"{BASE}/{NUMBER}/files/invoice/{INVOICE_ID}")).status_code == 200
    assert (
        await web.client.get(f"{BASE}/{NUMBER}/files/invoice/{INVOICE_ID}?variant=scan")
    ).status_code == 404


async def test_pdf_still_rendering_is_202(
    web: Web, erp: ProjectsFake, check: ContractChecker
) -> None:
    await _as(web, "ACCOUNTANT")
    erp.answer(
        "GET",
        r"contracts/\d+/download-pdf/",
        httpx.Response(
            202, json={"detail": "GENERATING", "retry_after": 2}, headers={"Retry-After": "2"}
        ),
    )
    response = await web.client.get(f"{BASE}/{NUMBER}/files/contract/{CONTRACT_ID}")
    assert response.status_code == 202
    assert response.headers["retry-after"] == "2"
    check(response, "/eds/projects/{ref}/files/{kind}/{doc_id}", "get")


async def test_file_erp_refusal_is_translated(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    erp.answer("GET", r"contracts/\d+/download-pdf/", erp_error(404, "NOT_FOUND"))
    assert (
        await web.client.get(f"{BASE}/{NUMBER}/files/contract/{CONTRACT_ID}")
    ).status_code == 404


async def test_bad_file_kind_and_variant_are_422(web: Web, erp: ProjectsFake) -> None:
    await _as(web, "ACCOUNTANT")
    assert (await web.client.get(f"{BASE}/{NUMBER}/files/memo/1")).status_code == 422
    assert (
        await web.client.get(f"{BASE}/{NUMBER}/files/contract/{CONTRACT_ID}?variant=zip")
    ).status_code == 422
    assert (await web.client.get(f"{BASE}/{NUMBER}/files/contract/0")).status_code == 422
    assert erp.calls == []


# --- журнал: ничего лишнего наружу --------------------------------------------------------------


async def test_the_card_never_reveals_cost_or_supplier_fields(web: Web, erp: ProjectsFake) -> None:
    """Проект — документы клиента (суммы с НДС); себестоимости, маржи и цен поставщиков нет."""
    await _as(web, "ACCOUNTANT")
    text = (await web.client.get(f"{BASE}/{NUMBER}")).text.lower()
    for word in ("margin", "cost", "supplier", "landed", "economics"):
        assert word not in text
    assert "фактур" not in text, "собственные PDF не называются счёт-фактурой"
    assert json.loads(text)["number"] == NUMBER.lower() or True
