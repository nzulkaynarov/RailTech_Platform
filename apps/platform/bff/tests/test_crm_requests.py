"""«+ Создать заявку» (W16-D1-2b, контракт BFF 0.27.0, тег `requests`): прокси к CRM и EDS.

CRM и EDS — на respx (`crm_leads_support`, `eds_documents_support`), ответы BFF сверяются со схемами
platform-bff.yaml. Проверяется то, что делает BFF: раздел `crm.clients` полный (и `crm.leads` для
вложения переписки; 403 — до CRM и EDS), выбор вызова CRM (лид или клиент), тело CRM без номера
лида, статус CRM (201 — новая, 200 — повтор формы), отказы CRM с кодом в `details.reason`,
«Повторить отправку в ERP», файл письма в EDS как есть и вложение переписки — формой multipart с
именем из CRM.
"""

import httpx
import pytest

from app.api import crm_requests
from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.crm_leads_support import LETTER_ID, REQUEST_KEY, CrmLeadsFake, created, request_form
from tests.eds_documents_support import FILE_ID, TOKEN, EdsFake
from tests.roles import custom
from tests.test_eds_documents import multipart

BASE = "/api/v1/crm/requests"
FILES = "/api/v1/crm/request-files"
FROM_MESSAGE = {"lead": "L-2041", "message": 90, "index": 0}


@pytest.fixture
def crm(be: Backends) -> CrmLeadsFake:
    return CrmLeadsFake(be)


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    return EdsFake(be)


async def _upload(web: Web, body: bytes, content_type: str) -> httpx.Response:
    return await web.client.post(
        FILES, content=body, headers={"content-type": content_type, CSRF_HEADER: web.csrf}
    )


# --- права ---------------------------------------------------------------------------------------


async def test_without_full_clients_nothing_reaches_crm_or_eds(
    web: Web, crm: CrmLeadsFake, eds: EdsFake
) -> None:
    await web.login(["SUPPLY"])  # клиенты — только чтение
    assert (await web.send("POST", BASE, json=request_form())).status_code == 403
    assert (await web.send("POST", f"{BASE}/78/retry")).status_code == 403
    assert (await web.send("POST", f"{FILES}/from-message", json=FROM_MESSAGE)).status_code == 403
    body, content_type = multipart()
    assert (await _upload(web, body, content_type)).status_code == 403
    assert crm.calls == []
    assert eds.calls == []
    assert eds.issued == []


async def test_copying_an_attachment_also_needs_the_leads_section(
    web: Web, crm: CrmLeadsFake, eds: EdsFake
) -> None:
    await web.login([custom(40, "Только клиенты", {"crm.clients": "full"})])
    response = await web.send("POST", f"{FILES}/from-message", json=FROM_MESSAGE)
    assert response.status_code == 403
    assert crm.calls == []
    assert eds.calls == []


# --- создать заявку ------------------------------------------------------------------------------


async def test_request_from_a_lead_goes_to_the_lead_action_of_crm(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = check(await web.send("POST", BASE, json=request_form()), "/crm/requests", "post")

    assert response.status_code == 201
    assert response.json() == {
        "client_id": 12,
        "deal": 77,
        "lead": "L-2041",
        "created": True,
        "transfer": "pending",
    }
    sent = crm.body("POST", "leads/2041/actions/create_request")
    assert "lead" not in sent
    assert sent["request_key"] == REQUEST_KEY
    assert sent["letter_file_id"] == LETTER_ID
    assert sent["consent"] == {"method": "phone", "comment": "по звонку"}
    assert sent["contact"]["use_lead_telegram"] is True
    assert (
        crm.last("POST", "leads/2041/actions/create_request")
        .headers["authorization"]
        .startswith("Bearer crm-access-")
    )


async def test_request_for_a_client_goes_to_the_client_action_of_crm(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    form = request_form(lead=None, client_id=12, company=None, consent=None)
    response = check(await web.send("POST", BASE, json=form), "/crm/requests", "post")

    assert response.status_code == 201
    assert crm.body("POST", "clients/12/actions/create_request")["client_id"] == 12


async def test_without_lead_and_client_it_is_422_before_crm(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = check(
        await web.send("POST", BASE, json=request_form(lead=None, client_id=None)),
        "/crm/requests",
        "post",
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"]["fields"] == ["client_id"]
    assert crm.calls == []


async def test_bad_form_is_422_before_crm(web: Web, crm: CrmLeadsFake) -> None:
    await web.login(["MANAGER"])
    for bad in (
        request_form(request_key="not-a-uuid"),
        request_form(summary=""),
        request_form(urgency="asap"),
        request_form(lead="2041"),
        request_form(consent={"method": "bot"}),
        request_form(extra="x"),
    ):
        assert (await web.send("POST", BASE, json=bad)).status_code == 422, bad
    assert crm.calls == []


async def test_repeat_of_the_form_is_200_with_the_same_request(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer(
        "POST",
        "leads/2041/actions/create_request",
        200,
        created(created=False, erp_request_status="done"),
    )
    await web.login(["MANAGER"])
    response = check(await web.send("POST", BASE, json=request_form()), "/crm/requests", "post")

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["transfer"] == "done"
    assert response.json()["deal"] == 77


async def test_no_consent_refusal_keeps_the_reason_of_crm(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.error(
        "POST",
        "leads/2041/actions/create_request",
        422,
        "validation_failed",
        reason="handoff_no_consent",
    )
    await web.login(["MANAGER"])
    response = check(
        await web.send("POST", BASE, json=request_form(consent=None)), "/crm/requests", "post"
    )
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "handoff_no_consent"


async def test_state_refusal_is_a_conflict_with_the_reason(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.error(
        "POST", "leads/2041/actions/create_request", 409, "conflict", reason="request_not_allowed"
    )
    await web.login(["MANAGER"])
    response = check(await web.send("POST", BASE, json=request_form()), "/crm/requests", "post")
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "request_not_allowed"


# --- повторить отправку в ERP ---------------------------------------------------------------------


async def test_retry_sends_the_request_to_erp_again(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = check(
        await web.send("POST", f"{BASE}/78/retry"), "/crm/requests/{deal}/retry", "post"
    )
    assert response.json() == {"deal": 78, "client_id": 12, "transfer": "pending"}
    assert crm.last("POST", "deals/78/actions/retry_request")


async def test_retry_of_a_request_not_in_error_is_a_conflict(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.error(
        "POST", "deals/77/actions/retry_request", 409, "conflict", reason="request_not_failed"
    )
    await web.login(["MANAGER"])
    response = check(
        await web.send("POST", f"{BASE}/77/retry"), "/crm/requests/{deal}/retry", "post"
    )
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "request_not_failed"


# --- письмо директору -----------------------------------------------------------------------------


async def test_letter_file_goes_to_eds_untouched(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    body, content_type = multipart()
    response = check(await _upload(web, body, content_type), "/crm/request-files", "post")

    assert response.status_code == 201
    assert response.json()["id"] == FILE_ID
    sent = eds.last("POST", "files")
    assert sent.content == body
    assert sent.headers["content-type"] == content_type
    assert sent.headers["authorization"].startswith(f"Bearer {TOKEN}")


async def test_letter_file_must_be_multipart(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = check(await _upload(web, b"{}", "application/json"), "/crm/request-files", "post")
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "multipart_required"
    assert eds.calls == []


async def test_attachment_of_the_conversation_is_copied_to_eds(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])  # лиды — чтение, клиенты — полный
    response = check(
        await web.send("POST", f"{FILES}/from-message", json=FROM_MESSAGE),
        "/crm/request-files/from-message",
        "post",
    )

    assert response.status_code == 201
    assert response.json()["id"] == FILE_ID
    sent = eds.last("POST", "files")
    assert sent.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b"%PDF-1.4 demo" in sent.content
    assert 'filename="З.pdf"'.encode() in sent.content
    assert b"Content-Type: application/pdf" in sent.content
    assert crm.last("GET", "leads/2041/messages/90/attachments/0")


async def test_missing_attachment_is_404_without_eds(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    body = {**FROM_MESSAGE, "index": 3}
    response = check(
        await web.send("POST", f"{FILES}/from-message", json=body),
        "/crm/request-files/from-message",
        "post",
    )
    assert response.status_code == 404
    assert eds.requests("POST", "files") == []


async def test_attachment_over_the_limit_is_413_without_eds(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crm_requests, "MAX_UPLOAD_BYTES", 4)
    await web.login(["MANAGER"])
    response = await web.send("POST", f"{FILES}/from-message", json=FROM_MESSAGE)
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert eds.requests("POST", "files") == []


def test_filename_prefers_utf8_and_falls_back_to_ascii() -> None:
    assert crm_requests.filename_of(
        "attachment; filename=\"_.pdf\"; filename*=UTF-8''%D0%97.pdf"
    ) == ("З.pdf")
    assert crm_requests.filename_of('attachment; filename="scan.png"') == "scan.png"
    assert crm_requests.filename_of("attachment") == "file"
