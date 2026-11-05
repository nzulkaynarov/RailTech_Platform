"""Письмо на бланке (P4 волны 18a, pg): проекция бланка ERP, тело блоками, PDF фоновым рендером на заглушке `rt-docs`
(кэш по хешу, параллельность 1, ошибка с причиной), передача на регистрацию исполнителем (B-P8B-4), регистрация ИСХ «в
ответ на» закрывает поручение, «Отправить адресату» через почтовый сервис CRM и журнал отправки по итогу CRM."""

import asyncio
import base64
import copy
import hashlib
from typing import Any

import httpx
import pytest

from app.container import Container
from app.services import letter_mail, renders
from app.services.render_process import TIMEOUT, RenderError
from app.services.storage import TEST_STORAGE
from tests.conftest import BUS_SECRET_CRM_EDS
from tests.domain import Person, deliver_erp, outbox, validate
from tests.helpers import example, signed
from tests.test_api_auth import assert_error
from tests.test_letter_instructions import BANK, register, resolve

pytestmark = pytest.mark.pg

PAIR = "test-pair-secret-eds-crm-".ljust(40, "x")
DUE = "2026-11-02"
PDF = b"%PDF-1.7 stub letter"

BODY: dict[str, Any] = {
    "version": 1,
    "lang": "ru",
    "doc": {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Направляем пояснения по требованию."}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "акт сверки"}]}],
                    }
                ],
            },
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Период"}]}],
                            },
                            {
                                "type": "tableHeader",
                                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Сумма"}]}],
                            },
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "III кв."}]}],
                            },
                            {
                                "type": "tableCell",
                                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "1 200 000"}]}],
                            },
                        ],
                    },
                ],
            },
        ],
    },
}


class StubRenderer:
    """Заглушка `rt-docs`: считает вызовы и одновременные рендеры, отдаёт фиксированный PDF или ошибку."""

    def __init__(self, *, delay: float = 0.0, fail: str | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.logos: list[bytes | None] = []
        self.active = 0
        self.max_active = 0
        self.delay = delay
        self.fail = fail

    async def __call__(self, payload: dict[str, Any], logo: bytes | None, mime: str | None) -> dict[str, Any]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            self.calls.append(payload)
            self.logos.append(logo)
            if self.fail:
                raise RenderError(self.fail, "stub")
            return {"pdf": PDF, "pages": 1, "last_page_fill": 0.4, "warnings": []}
        finally:
            self.active -= 1


async def deliver_letterhead(client: httpx.AsyncClient, container: Container, **changes: Any) -> dict[str, Any]:
    envelope = example("erp/letterhead.updated.v1")
    envelope["data"]["letterhead"].update(changes)
    assert await deliver_erp(client, container, envelope) == "processed"
    return envelope


def letter_json(**changes: Any) -> dict[str, Any]:
    return {
        "kind": "letter_out",
        "subject": "Ответ на требование",
        "text": "—",
        "recipient": {"name": "ГНИ Мирабадского района"},
        "letter": {
            "body": copy.deepcopy(BODY),
            "recipient_attention": "Начальнику инспекции Каримову А. А.",
            "recipient_email": "gni@example.org",
        },
        **changes,
    }


async def run(container: Container, renderer: StubRenderer, render_hash: str) -> str | None:
    return await renders.run(
        container.session_factory,
        TEST_STORAGE,
        renderer,
        render_hash,
        on_finished=letter_mail.on_render_finished(container.bus, TEST_STORAGE),
    )


async def test_letterhead_projection_keeps_the_newest_snapshot(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    empty = (await client.get("/api/v1/letterhead", headers=staff["manager"].headers)).json()
    validate("Letterhead", empty)
    assert empty["configured"] is False

    envelope = await deliver_letterhead(client, container)
    shown = (await client.get("/api/v1/letterhead", headers=staff["manager"].headers)).json()
    validate("Letterhead", shown)
    assert (shown["configured"], shown["company_name"], shown["has_logo"]) == (True, "ООО «RailTech»", True)
    assert shown["signatory_name"] == "Каримов А. А."
    assert "ИНН 305123456" in shown["requisites"]

    older = copy.deepcopy(envelope)
    older["id"], older["time"] = "6b0e3c8a-6f1d-4c2e-9a7b-3d2f1e0c9b8a", "2026-11-01T06:00:00Z"
    older["data"]["letterhead"]["company_name"] = "Старое имя"
    assert await deliver_erp(client, container, older) == "processed"
    again = (await client.get("/api/v1/letterhead", headers=staff["manager"].headers)).json()
    assert again["company_name"] == "ООО «RailTech»"


async def test_letterhead_with_forged_logo_is_rejected(client: httpx.AsyncClient, container: Container) -> None:
    envelope = example("erp/letterhead.updated.v1")
    envelope["data"]["letterhead"]["logo"]["sha256"] = "0" * 64
    assert await deliver_erp(client, container, envelope) != "processed"


async def test_pdf_cache_failure_and_letterhead_missing(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    manager = staff["manager"]
    created = await client.post("/api/v1/documents", json=letter_json(), headers=manager.headers)
    assert created.status_code == 201, created.text
    doc = created.json()
    validate("Document", doc)
    assert doc["text"].startswith("Направляем пояснения") and "Период Сумма" in doc["text"]
    assert doc["letter"]["recipient_email"] == "gni@example.org" and doc["letter"]["pdf"] is None

    no_head = await client.post(f"/api/v1/documents/{doc['id']}/pdf", headers=manager.headers)
    assert_error(no_head, 409, "CONFLICT", reason="letterhead_missing")
    await deliver_letterhead(client, container)

    first = await client.post(f"/api/v1/documents/{doc['id']}/pdf", headers=manager.headers)
    assert first.status_code == 202, first.text
    validate("DocumentPdf", first.json())
    assert (first.json()["status"], first.json()["final"]) == ("pending", False)
    assert len(deferred) == 1
    render_hash = deferred[0]
    file_early = await client.get(f"/api/v1/documents/{doc['id']}/pdf/file", headers=manager.headers)
    assert_error(file_early, 409, "CONFLICT", reason="pdf_not_ready")

    stub = StubRenderer()
    assert await run(container, stub, render_hash) == "ready"
    assert await run(container, stub, render_hash) is None  # уже готов — второго рендера нет
    assert len(stub.calls) == 1
    payload = stub.calls[0]
    assert payload["meta"]["number"] is None and payload["meta"]["addressee"] == [
        "Начальнику инспекции Каримову А. А.",
        "ГНИ Мирабадского района",
    ]
    assert payload["body"]["doc"]["content"][-1] == {
        "type": "signature",
        "attrs": {"parties": [{"position": "Директор", "name": "Каримов А. А."}]},
    }
    assert payload["letterhead"]["company_name"] == "ООО «RailTech»" and stub.logos[0] is not None

    status = (await client.get(f"/api/v1/documents/{doc['id']}/pdf", headers=manager.headers)).json()
    assert (status["status"], status["pages"]) == ("ready", 1)
    pdf = await client.get(f"/api/v1/documents/{doc['id']}/pdf/file", headers=manager.headers)
    assert pdf.status_code == 200 and pdf.content == PDF
    assert pdf.headers["content-type"] == "application/pdf" and pdf.headers["etag"] == f'"{render_hash}"'

    # Кэш по хешу: тот же ввод — тот же PDF без постановки; другой текст — новый хеш.
    cached = await client.post(f"/api/v1/documents/{doc['id']}/pdf", headers=manager.headers)
    assert cached.json()["status"] == "ready" and len(deferred) == 1
    body = copy.deepcopy(BODY)
    body["doc"]["content"][0]["content"][0]["text"] = "Другой текст."
    edited = await client.patch(
        f"/api/v1/documents/{doc['id']}", json={"letter": {"body": body}}, headers=manager.headers
    )
    assert edited.status_code == 200, edited.text
    await client.post(f"/api/v1/documents/{doc['id']}/pdf", headers=manager.headers)
    assert len(deferred) == 2 and deferred[1] != render_hash

    failing = StubRenderer(fail=TIMEOUT)
    assert await run(container, failing, deferred[1]) == "failed"
    failed = (await client.get(f"/api/v1/documents/{doc['id']}/pdf", headers=manager.headers)).json()
    assert failed["status"] == "failed" and "слишком большое" in failed["error"]
    retried = await client.post(f"/api/v1/documents/{doc['id']}/pdf", headers=manager.headers)
    assert retried.json()["status"] == "pending" and deferred[-1] == deferred[1]


async def test_invalid_body_is_rejected(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    body = copy.deepcopy(BODY)
    body["doc"]["content"].append({"type": "paragraph", "attrs": {"style": "color:red"}})
    response = await client.post(
        "/api/v1/documents", json=letter_json(letter={"body": body}), headers=staff["manager"].headers
    )
    assert_error(response, 422, "VALIDATION_FAILED")
    memo = await client.post(
        "/api/v1/documents",
        json={"kind": "memo", "subject": "x", "text": "y", "letter": {"body": BODY}},
        headers=staff["manager"].headers,
    )
    assert_error(memo, 422, "VALIDATION_FAILED")


async def test_renders_run_one_at_a_time(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    """B-094: параллельность 1 — два рендера одновременно не идут (в процессе — замок, между процессами — `lock`)."""
    from app.tasks.renders import LOCK, render_pdf

    assert render_pdf.lock == LOCK and render_pdf.queue == "renders"
    await deliver_letterhead(client, container)
    for text in ("Первое", "Второе"):
        body = copy.deepcopy(BODY)
        body["doc"]["content"][0]["content"][0]["text"] = text
        doc = (
            await client.post(
                "/api/v1/documents", json=letter_json(letter={"body": body}), headers=staff["manager"].headers
            )
        ).json()
        await client.post(f"/api/v1/documents/{doc['id']}/pdf", headers=staff["manager"].headers)
    stub = StubRenderer(delay=0.05)
    results = await asyncio.gather(*(run(container, stub, h) for h in deferred))
    assert results == ["ready", "ready"] and stub.max_active == 1


async def test_executor_hands_over_registrar_registers_closes_instruction_and_mails(
    client: httpx.AsyncClient,
    staff: dict[str, Person],
    container: Container,
    deferred: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сценарий «готово, когда»: поручение «Подготовить ответ» менеджеру без `letters.register` → черновик на бланке →
    «Передать на регистрацию» → делопроизводитель регистрирует ИСХ и отправляет адресату → поручение закрыто →
    итоговый PDF
    → `mail.requested` в CRM → итог CRM «Почта не настроена» в журнале отправки → повтор → «отправлено»."""
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)
    registrar, director, manager = staff["registrar"], staff["director"], staff["manager"]
    await deliver_letterhead(client, container)
    incoming = await register(client, registrar, BANK, sender_ref={"number": "12-04/551", "date": "2026-10-24"})
    resolved = await resolve(
        client, director, incoming["id"], kind="reply", text="Ответить банку", responsible_crm_user_id=5, due=DUE
    )
    assert resolved.status_code == 200, resolved.text

    created = await client.post(
        "/api/v1/documents", json=letter_json(in_reply_to=incoming["id"]), headers=manager.headers
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]
    # делопроизводитель чужой черновик не видит, пока его не передали
    assert_error(await client.get(f"/api/v1/documents/{doc_id}", headers=registrar.headers), 404, "NOT_FOUND")
    preview = await client.post(f"/api/v1/documents/{doc_id}/pdf", headers=manager.headers)
    assert preview.status_code == 202
    draft_payload = (StubRenderer(), deferred[-1])
    assert await run(container, *draft_payload) == "ready"
    assert draft_payload[0].calls[0]["meta"]["reply_to"] == "№ 12-04/551 от 24.10.2026"

    handed = await client.post(f"/api/v1/documents/{doc_id}/registration-request", headers=manager.headers)
    assert handed.status_code == 200, handed.text
    validate("Document", handed.json())
    assert handed.json()["letter"]["registration_requested"]["by"]["crm_user_id"] == 5
    assert_error(
        await client.post(f"/api/v1/documents/{doc_id}/submit", headers=manager.headers),
        403,
        "FORBIDDEN",
        permission="letters.register",
    )

    seen = await client.get(f"/api/v1/documents/{doc_id}", headers=registrar.headers)
    assert seen.status_code == 200
    registered = await client.post(f"/api/v1/documents/{doc_id}/submit", json={"send": True}, headers=registrar.headers)
    assert registered.status_code == 200, registered.text
    card = registered.json()
    validate("Document", card)
    assert card["status"] == "sent" and card["number"].startswith("ИСХ-")
    assert card["letter"]["pdf"]["final"] is True and card["letter"]["pdf"]["status"] == "pending"
    [mailing] = card["letter"]["mailings"]
    assert (mailing["status"], mailing["to"]) == ("awaiting_pdf", ["gni@example.org"])
    # ИСХ «в ответ на» закрыл поручение «Подготовить ответ»
    letter_card = (await client.get(f"/api/v1/letters/{incoming['id']}", headers=director.headers)).json()
    assert letter_card["status"] == "executed"
    assert letter_card["instructions"][0]["outgoing"]["number"] == card["number"]

    final = StubRenderer()
    assert await run(container, final, deferred[-1]) == "ready"
    assert final.calls[0]["meta"]["number"] == card["number"] and final.calls[0]["meta"]["date"] == "2026-10-26"
    [requested] = await outbox(container, "mail.requested")
    data = requested["data"]
    assert data["notify"] is True and data["purpose"] == "outgoing_letter"
    assert data["ref"] == {"kind": "document", "id": doc_id} and data["to"] == ["gni@example.org"]
    assert data["attachments"][0]["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert card["number"] in data["subject"]

    await deliver_crm(client, container, "mail.failed", data["request_key"], reason="smtp_not_configured")
    after = (await client.get(f"/api/v1/documents/{doc_id}", headers=registrar.headers)).json()
    validate("Document", after)
    assert after["letter"]["mailings"][0]["status"] == "failed"
    assert after["letter"]["mailings"][0]["reason"] == "Почта не настроена — Настройки · Подключения · Почта"

    again = await client.post(f"/api/v1/documents/{doc_id}/send", headers=registrar.headers)
    assert again.status_code == 200, again.text
    second = again.json()["letter"]["mailings"][-1]
    assert second["status"] == "requested"  # итоговый PDF уже готов — запрос в CRM сразу
    busy = await client.post(f"/api/v1/documents/{doc_id}/send", headers=registrar.headers)
    assert_error(busy, 409, "CONFLICT", reason="mail_in_progress")
    key = (await outbox(container, "mail.requested"))[-1]["data"]["request_key"]
    await deliver_crm(client, container, "mail.sent", key)
    done = (await client.get(f"/api/v1/documents/{doc_id}", headers=registrar.headers)).json()
    assert [m["status"] for m in done["letter"]["mailings"]] == ["failed", "sent"]
    actions = [entry["action"] for entry in done["journal"]]
    assert "document.registration_requested" in actions and "document.mail_sent" in actions


async def test_send_requires_email_and_registrar(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, deferred: list[str]
) -> None:
    await deliver_letterhead(client, container)
    registrar = staff["registrar"]
    letter = letter_json()
    letter["letter"]["recipient_email"] = None
    doc = (await client.post("/api/v1/documents", json=letter, headers=registrar.headers)).json()
    no_mail = await client.post(f"/api/v1/documents/{doc['id']}/submit", json={"send": True}, headers=registrar.headers)
    assert_error(no_mail, 422, "VALIDATION_FAILED")
    plain = await client.post(f"/api/v1/documents/{doc['id']}/submit", headers=registrar.headers)
    assert plain.status_code == 200 and plain.json()["letter"]["mailings"] == []
    assert_error(
        await client.post(f"/api/v1/documents/{doc['id']}/send", headers=staff["manager"].headers),
        403,
        "FORBIDDEN",
    )
    assert_error(
        await client.post(f"/api/v1/documents/{doc['id']}/send", headers=registrar.headers), 422, "VALIDATION_FAILED"
    )


async def deliver_crm(
    client: httpx.AsyncClient, container: Container, kind: str, request_key: str, **changes: Any
) -> None:
    envelope = example(f"crm/{kind}.v1")
    envelope["data"].update(requester="eds", request_key=request_key, purpose="outgoing_letter", **changes)
    envelope["data"].pop("ref", None)
    headers, body = signed(envelope, publisher="crm", secret=BUS_SECRET_CRM_EDS)
    response = await client.post("/bus/v1/events", headers=headers, content=body)
    assert response.status_code == 200, response.text
    assert await container.bus.process_inbox(envelope["id"]) == "processed"


def test_logo_bytes_of_the_example_are_a_png() -> None:
    logo = example("erp/letterhead.updated.v1")["data"]["letterhead"]["logo"]
    raw = base64.b64decode(logo["data_base64"])
    assert raw.startswith(b"\x89PNG") and hashlib.sha256(raw).hexdigest() == logo["sha256"]
