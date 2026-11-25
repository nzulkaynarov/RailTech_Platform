"""«+ Создать заявку» (W16-D1-2b, контракт BFF, тег `requests`): прокси к CRM и EDS.

CRM и EDS — на respx (`crm_leads_support`, `eds_documents_support`), ответы BFF сверяются со схемами
platform-bff.yaml. Проверяется то, что делает BFF: раздел `crm.clients` полный (и `crm.leads` для
вложения переписки; 403 — до CRM и EDS), выбор вызова CRM (лид или клиент), тело CRM без номера
лида, статус CRM (201 — новая, 200 — повтор формы), отказы CRM с кодом в `details.reason`,
«Повторить отправку в ERP», файл письма в EDS как есть и вложение переписки — формой multipart с
именем из CRM; записка о звонке (СЦ-6) — лид из CRM (канал, согласие), поля в EDS и ответ EDS.
"""

from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
import yaml

from app.api import crm_requests
from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.crm_leads_support import LETTER_ID, REQUEST_KEY, CrmLeadsFake, created, request_form
from tests.eds_documents_support import FILE_ID, TOKEN, EdsFake, file_ref
from tests.messages_support import EARLIER, NOW, lead_detail, message
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
        request_form(letter_file_id=None),  # plan 0.4 (FR-9): no basis — no request
        {k: v for k, v in request_form().items() if k != "letter_file_id"},
    ):
        assert (await web.send("POST", BASE, json=bad)).status_code == 422, bad
    assert crm.calls == []


PARTNER_FORM = {
    "company_name": "Контур Партнёр",
    "country": "uz",
    "inn": "301234567",
    "offer": "Поставляем крепёж",
    "contact_name": "Иван Партнёров",
    "email": "ivan@partner.example",
    "phone": "",
}
PARTNER = "leads/2041/actions/hand_over_partner"


async def test_partner_answer_goes_to_the_partner_action_of_crm(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer("POST", PARTNER, 201, {"lead_id": 2041, "application_id": 7001, "created": True})
    await web.login(["MANAGER"])
    response = check(
        await web.send("POST", "/api/v1/crm/leads/L-2041/partner", json=PARTNER_FORM),
        "/crm/leads/{lead}/partner",
        "post",
    )

    assert response.status_code == 201
    assert response.json() == {"lead": "L-2041", "application": 7001, "created": True}
    assert crm.body("POST", PARTNER)["company_name"] == "Контур Партнёр"


async def test_second_partner_answer_is_200_with_the_first_application(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer("POST", PARTNER, 200, {"lead_id": 2041, "application_id": 7001, "created": False})
    await web.login(["MANAGER"])
    response = check(
        await web.send("POST", "/api/v1/crm/leads/L-2041/partner", json=PARTNER_FORM),
        "/crm/leads/{lead}/partner",
        "post",
    )
    assert response.status_code == 200
    assert response.json() == {"lead": "L-2041", "application": 7001, "created": False}


async def test_partner_answer_without_full_clients_does_not_reach_crm(
    web: Web, crm: CrmLeadsFake
) -> None:
    await web.login(["SUPPLY"])
    response = await web.send("POST", "/api/v1/crm/leads/L-2041/partner", json=PARTNER_FORM)
    assert response.status_code == 403
    assert crm.calls == []


async def test_partner_without_email_is_422_before_crm(web: Web, crm: CrmLeadsFake) -> None:
    """Phone-only candidates cannot be invited to the contract: the e-mail is required."""
    await web.login(["MANAGER"])
    bad = {k: v for k, v in PARTNER_FORM.items() if k != "email"}
    response = await web.send("POST", "/api/v1/crm/leads/L-2041/partner", json=bad)
    assert response.status_code == 422
    assert crm.calls == []


async def test_partner_invalid_email_of_crm_is_a_field_error(web: Web, crm: CrmLeadsFake) -> None:
    crm.error("POST", PARTNER, 422, "validation_failed", reason="invalid_email", field="email")
    await web.login(["MANAGER"])
    response = await web.send("POST", "/api/v1/crm/leads/L-2041/partner", json=PARTNER_FORM)
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "invalid_email"


async def test_partner_refusal_of_crm_keeps_its_reason(web: Web, crm: CrmLeadsFake) -> None:
    crm.error("POST", PARTNER, 503, "upstream_unavailable", reason="erp_unavailable")
    await web.login(["MANAGER"])
    response = await web.send("POST", "/api/v1/crm/leads/L-2041/partner", json=PARTNER_FORM)
    assert response.status_code == 503


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


# --- записка о звонке (СЦ-6) ---------------------------------------------------------------------

NOTE = f"{FILES}/call-note"
NOTE_ID = "50000000-0000-4000-8000-000000000001"
PENDING = {"id": NOTE_ID, "status": "pending", "error": None, "file": None}
READY = {"id": NOTE_ID, "status": "ready", "error": None, "file": file_ref()}


def note_form(**over: object) -> dict[str, object]:
    return {"request_key": REQUEST_KEY, "lang": "ru", "lead": "L-2041", **over}


def phone_lead(crm: CrmLeadsFake, **over: object) -> None:
    crm.answer(
        "GET",
        "leads/2041",
        200,
        lead_detail(
            2041,
            **{
                "source": "phone",
                "assigned_user_id": 7,
                "assigned_user_name": "Дилшод Менеджеров",
                "display_name": "Азиз Звонкий",
                "company_name": "ООО Звонок",
                "phone_e164": "+998901112233",
                "email": "aziz@example.org",
                "need_summary": "Рельсы Р65, 40 т",
                **over,
            },
        ),
    )


async def test_note_of_a_phone_lead_goes_to_eds_with_the_lead_fields(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    phone_lead(crm)
    eds.answer("POST", "call-notes", 202, PENDING)
    # Данные записки берутся из лида: подмена «кто звонил» в теле не доходит до EDS.
    body = note_form(caller={"name": "Чужое имя"}, need="чужое")
    response = check(
        await web.send("POST", NOTE, json=body), "/crm/request-files/call-note", "post"
    )

    assert response.status_code == 202
    assert response.json() == PENDING
    sent = eds.body("POST", "call-notes")
    note_key = sent.pop("request_key")
    assert sent == {
        "channel": "phone",
        "message": None,
        "attachments": [],
        "lang": "ru",
        "lead": "L-2041",
        "caller_name": "Азиз Звонкий",
        "company": "ООО Звонок",
        "phone": "+998901112233",
        "email": "aziz@example.org",
        "called_at": EARLIER.replace("Z", "+00:00"),
        "taken_by": "Дилшод Менеджеров",
        "need": "Рельсы Р65, 40 т",
    }
    # Ключ записки выводится из лида: повторное открытие формы (другой ключ) — та же записка.
    again = note_form(request_key="60000000-0000-4000-8000-000000000009")
    assert (await web.send("POST", NOTE, json=again)).status_code == 202
    assert eds.body("POST", "call-notes")["request_key"] == note_key
    assert eds.last("POST", "call-notes").headers["authorization"].startswith(f"Bearer {TOKEN}")


@pytest.mark.parametrize("source", ["web", "cabinet", "telegram"])
async def test_note_of_a_lead_of_any_channel_carries_its_message_and_attachments(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker, source: str
) -> None:
    """Х-18: one rule for every channel - no file needed, the basis is built from the lead."""
    await web.login(["MANAGER"])
    phone_lead(crm, source=source)
    crm.answer(
        "GET",
        "leads/2041/messages",
        200,
        [
            message(95, "lead", text="Второе", created_at=NOW),
            message(
                90,
                "lead",
                text="Нужны рельсы Р65",
                attachments=[{"kind": "file", "name": "ТЗ.pdf", "stored": True}, {"kind": "photo"}],
            ),
            message(91, "bot", text="Ответ бота"),
        ],
    )
    eds.answer("POST", "call-notes", 202, PENDING)
    response = check(
        await web.send("POST", NOTE, json=note_form()), "/crm/request-files/call-note", "post"
    )
    assert response.status_code == 202
    sent = eds.body("POST", "call-notes")
    assert sent["channel"] == source
    assert sent["message"] == "Нужны рельсы Р65"
    assert sent["attachments"] == ["ТЗ.pdf"]
    assert sent["lead"] == "L-2041"


EDS_CONTRACT = Path(__file__).resolve().parents[4] / "packages/contracts/openapi/eds.yaml"


def _eds_call_note_schema() -> dict[str, Any]:
    spec = yaml.safe_load(EDS_CONTRACT.read_text(encoding="utf-8"))
    return {**spec["components"]["schemas"]["CallNoteIn"], "components": spec["components"]}


async def test_note_of_a_lead_with_hostile_input_still_passes_the_eds_contract(
    web: Web, crm: CrmLeadsFake, eds: EdsFake
) -> None:
    """A 4096-char Telegram message, 25 files, a 300-char name: EDS must not answer 422."""
    await web.login(["MANAGER"])
    phone_lead(crm, source="telegram", display_name="Я" * 300, company_name="К" * 255)
    crm.answer(
        "GET",
        "leads/2041/messages",
        200,
        [
            message(
                90,
                "lead",
                text="Ж" * 4096,
                attachments=[{"kind": "file", "name": f"{'ф' * 234}{i}.pdf"} for i in range(25)]
                + [{"kind": "file", "name": "   "}],
            )
        ],
    )
    eds.answer("POST", "call-notes", 202, PENDING)
    assert (await web.send("POST", NOTE, json=note_form())).status_code == 202
    sent = eds.body("POST", "call-notes")
    jsonschema.Draft202012Validator(_eds_call_note_schema()).validate(sent)
    assert sent["message"].endswith("…")
    assert len(sent["message"]) == 4000
    assert len(sent["attachments"]) == 20


async def test_the_original_message_is_found_on_an_earlier_page_of_a_long_thread(
    web: Web, crm: CrmLeadsFake, eds: EdsFake
) -> None:
    """CRM gives the last 200 messages: the first client message is paged back by before_id."""
    await web.login(["MANAGER"])
    phone_lead(crm, source="telegram")
    last_page = [message(1000 + i, "bot", text=f"бот {i}") for i in range(200)]
    first_page = [message(900, "lead", text="Самое первое"), message(901, "bot", text="Привет")]

    def thread(request: httpx.Request) -> httpx.Response:
        before = request.url.params.get("before_id")
        return httpx.Response(200, json=last_page if before is None else first_page)

    crm.overrides[("GET", "/api/v1/leads/2041/messages")] = thread
    eds.answer("POST", "call-notes", 202, PENDING)
    assert (await web.send("POST", NOTE, json=note_form())).status_code == 202
    assert eds.body("POST", "call-notes")["message"] == "Самое первое"


async def test_note_of_a_lead_without_thread_access_is_still_built_from_the_lead(
    web: Web, crm: CrmLeadsFake, eds: EdsFake
) -> None:
    await web.login(["MANAGER"])
    phone_lead(crm, source="web")
    crm.error("GET", "leads/2041/messages", 403, "FORBIDDEN")
    eds.answer("POST", "call-notes", 202, PENDING)
    response = await web.send("POST", NOTE, json=note_form())
    assert response.status_code == 202
    sent = eds.body("POST", "call-notes")
    assert (sent["channel"], sent["message"], sent["attachments"]) == ("web", None, [])


async def test_note_without_consent_waits_for_the_mark_in_the_form(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    phone_lead(crm, consent_given_at=None)
    eds.answer("POST", "call-notes", 202, PENDING)
    refused = check(
        await web.send("POST", NOTE, json=note_form()), "/crm/request-files/call-note", "post"
    )
    assert refused.status_code == 409
    assert refused.json()["details"]["reason"] == "call_note_no_consent"
    assert eds.requests("POST", "call-notes") == []

    marked = await web.send("POST", NOTE, json=note_form(consent=True))
    assert marked.status_code == 202
    assert len(eds.requests("POST", "call-notes")) == 1


async def test_note_without_a_lead_is_made_from_the_form_fields(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    eds.answer("POST", "call-notes", 202, PENDING)
    body = {
        "request_key": REQUEST_KEY,
        "lang": "uz",
        "caller": {
            "name": "Ольга Почтова",
            "company": "ООО Дальний",
            "phone": None,
            "email": "o@x.org",
        },
        "need": "Повторный заказ",
    }
    response = check(
        await web.send("POST", NOTE, json=body), "/crm/request-files/call-note", "post"
    )

    assert response.status_code == 202
    sent = eds.body("POST", "call-notes")
    assert sent["lead"] is None
    assert sent["taken_by"] is None
    assert (sent["caller_name"], sent["company"], sent["email"], sent["need"]) == (
        "Ольга Почтова",
        "ООО Дальний",
        "o@x.org",
        "Повторный заказ",
    )
    assert sent["lang"] == "uz"
    assert sent["called_at"]
    assert crm.calls == []


async def test_note_without_a_lead_needs_the_caller(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    body = {"request_key": REQUEST_KEY, "lang": "ru"}
    response = check(
        await web.send("POST", NOTE, json=body), "/crm/request-files/call-note", "post"
    )
    assert response.status_code == 422
    assert response.json()["details"]["fields"] == ["caller"]
    assert eds.requests("POST", "call-notes") == []


async def test_note_without_a_letterhead_keeps_the_reason_of_eds(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    phone_lead(crm)
    eds.error(
        "POST", "call-notes", 409, "CONFLICT", "Нет бланка.", {"reason": "letterhead_missing"}
    )
    response = check(
        await web.send("POST", NOTE, json=note_form()), "/crm/request-files/call-note", "post"
    )
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "letterhead_missing"


async def test_note_state_is_read_from_eds_and_foreign_note_is_404(
    web: Web, crm: CrmLeadsFake, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    eds.answer("GET", f"call-notes/{NOTE_ID}", 200, READY)
    response = check(
        await web.client.get(f"{NOTE}/{NOTE_ID}"), "/crm/request-files/call-note/{note}", "get"
    )
    assert response.status_code == 200
    assert response.json()["file"]["id"] == FILE_ID

    other = "50000000-0000-4000-8000-000000000002"
    eds.error("GET", f"call-notes/{other}", 404, "NOT_FOUND")
    assert (await web.client.get(f"{NOTE}/{other}")).status_code == 404
    assert (await web.client.get(f"{NOTE}/not-a-uuid")).status_code == 422


async def test_note_needs_full_clients_section(web: Web, crm: CrmLeadsFake, eds: EdsFake) -> None:
    await web.login(["SUPPLY"])
    assert (await web.send("POST", NOTE, json=note_form())).status_code == 403
    assert (await web.client.get(f"{NOTE}/{NOTE_ID}")).status_code == 403
    assert crm.calls == []
    assert eds.calls == []


async def test_request_file_is_opened_from_eds_as_an_attachment(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    response = await web.client.get(f"{FILES}/{FILE_ID}")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 demo"
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (
        eds.last("GET", f"files/{FILE_ID}").headers["authorization"].startswith(f"Bearer {TOKEN}")
    )

    eds.error("GET", f"files/{FILE_ID}", 404, "NOT_FOUND")
    assert (await web.client.get(f"{FILES}/{FILE_ID}")).status_code == 404


async def test_request_file_needs_full_clients_section(web: Web, eds: EdsFake) -> None:
    await web.login(["SUPPLY"])
    assert (await web.client.get(f"{FILES}/{FILE_ID}")).status_code == 403
    assert eds.calls == []
