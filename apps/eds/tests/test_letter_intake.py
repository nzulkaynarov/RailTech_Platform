"""«Заполнить из файла» (EDS-REG, PD-BIZ, pg): PDF с текстом — в модель уходит маскированный текст по политике защиты
данных («Деловая» по умолчанию, «Строгая» — прежнее поведение; политика приходит событием CRM и действует сразу, без
перезапуска), номера возвращает код; скан — при «Деловой» и включённом «Распознавать сканы», при «Строгой» отказ; вид —
из справочника; ИНН — из текста кодом; журнал без текстов; настройки — у администратора. Модель — подмена транспорта
(`httpx.MockTransport`), платных вызовов нет."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.ai import gateway, provision
from app.config import Settings
from app.container import Container
from app.models import AiSuggestion, JournalEntry
from app.services import letter_intake
from app.services.letter_intake import find_inn, pdf_text
from tests.conftest import BUS_SECRET_CRM_EDS
from tests.domain import Person, validate
from tests.helpers import example, signed
from tests.test_api_auth import assert_error
from tests.test_files import PNG, upload

pytestmark = pytest.mark.pg

LETTER_LINES = [
    "Tax Committee of Demo District",
    "Ref. No. 1234567/KC dated 2026-10-20",
    "To: Demo Rail LLC, INN 301234567",
    "Subject: explanation of VAT discrepancy for Q3",
    "Please provide explanations by 2026-11-10. Contact: +998 90 123 45 67, inspector@example.uz",
]


def make_pdf(lines: list[str], pages: int = 1) -> bytes:
    """Минимальный PDF с текстовым слоем (Helvetica, латиница) — для разбора `pypdf`; все страницы с одним текстом."""
    stream = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    kids = " ".join(f"{5 + i} 0 R" for i in range(pages))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ] + [
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 3 0 R /Resources << /Font << /F1 4 0 R >> >> >>"
    ] * pages
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


ANSWER: dict[str, Any] = {
    "sender_name": "Tax Committee of Demo District",
    "sender_ref_number": "[number_1]/KC",
    "sender_ref_date": "2026-10-20",
    "subject": "VAT discrepancy for Q3",
    "summary": "Asks to explain the VAT discrepancy by 10 November.",
    "kind": "tax_notice",
    "document_due": "2026-11-10",
}


class FakeModel:
    """Шлюз LiteLLM: запоминает тела запросов, отвечает заданным JSON."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.answer: dict[str, Any] = ANSWER
        self.status = 200
        self.failure: str | None = None  # "500" · "timeout" · "junk" — настоящие сбои модели (не лимит)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        if self.failure == "timeout":
            raise httpx.ReadTimeout("model is silent", request=request)
        if self.failure == "500":
            return httpx.Response(500, text="upstream exploded")
        if self.failure == "junk":
            junk = {"choices": [{"message": {"content": "not json at all"}, "finish_reason": "stop"}]}
            return httpx.Response(200, json=junk)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"type": "budget_exceeded"}})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(self.answer)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 120},
            },
            headers={gateway.COST_HEADER: "0.0004"},
        )


@pytest.fixture
def model(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    fake = FakeModel()
    monkeypatch.setattr(gateway, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(settings, "litellm_api_key", SecretStr("sk-test-eds-key"))
    return fake


async def intake(
    client: httpx.AsyncClient,
    who: Person,
    content: bytes,
    received_at: str | None = None,
    rules_only: bool = False,
    **kw: Any,
) -> httpx.Response:
    uploaded = await upload(client, who, content, **kw)
    assert uploaded.status_code == 201, uploaded.text
    body = {
        "file_id": uploaded.json()["id"],
        **({"received_at": received_at} if received_at else {}),
        **({"rules_only": True} if rules_only else {}),
    }
    return await client.post("/api/v1/letter-intake", json=body, headers=who.headers)


async def deliver_policy(
    client: httpx.AsyncClient, container: Container, policy: str, *, at: str = "2026-11-03T09:00:00Z"
) -> str | None:
    """Политика защиты данных из CRM: подписанная доставка события приёмнику и обработка inbox (как в проде)."""
    envelope = example("crm/ai_policy.changed.v1")
    envelope["data"].update(pii_policy=policy, changed_at=at)
    headers, body = signed(envelope, publisher="crm", secret=BUS_SECRET_CRM_EDS)
    response = await client.post("/bus/v1/events", headers=headers, content=body)
    assert response.status_code == 200, response.text
    return await container.bus.process_inbox(envelope["id"])


BUSINESS_PERSONAL = (
    "Director passport AA1234567, PINFL 31234567890123, card 4111 1111 1111 1111, birth date: 12.03.1985, "
    "account 20208000900123456001"
)


def test_pdf_text_and_inn_are_read_by_code() -> None:
    text = pdf_text(make_pdf(LETTER_LINES))
    assert "Ref. No. 1234567/KC" in text
    assert find_inn(text) == "301234567"
    assert find_inn("ПИНФЛ 31234567890123, тел. 901234567") is None  # личный номер и телефон — не ИНН
    # Свой ИНН (реквизиты адресата в письме) — не ИНН отправителя.
    assert find_inn("Кому: ООО «Демо», ИНН 309999999. От: банк, ИНН 301234567", own="309999999") == "301234567"
    assert pdf_text(b"%PDF-1.4 broken") == ""


async def test_text_pdf_goes_masked_and_numbers_come_back(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, container: Container
) -> None:
    """«Строгая» — прежнее поведение: номера, телефон и почта в модель не уходят."""
    assert await deliver_policy(client, container, "strict") == "processed"
    response = await intake(client, staff["registrar"], make_pdf(LETTER_LINES), name="letter.pdf")
    assert response.status_code == 200, response.text
    body = response.json()
    validate("LetterIntakeSuggestion", body)
    assert (body["source"], body["alias"]) == ("text", "intake-model")
    fields = body["fields"]
    assert fields["sender_ref_number"] == "1234567/KC"  # метка вернулась кодом, локально
    assert fields["sender_inn"] == "301234567"  # ИНН нашёл код, не модель
    assert (fields["kind"], fields["document_due"], fields["sender_ref_date"]) == (
        "tax_notice",
        "2026-11-10",
        "2026-10-20",
    )

    sent = json.dumps(model.bodies[0], ensure_ascii=False)
    for secret in ("1234567", "301234567", "+998 90 123 45 67", "inspector@example.uz"):
        assert secret not in sent  # персональные данные и номера в модель не ушли
    assert "[number_1]/KC" in sent and "[email]" in sent
    assert model.bodies[0]["model"] == "intake-model"
    assert "tax_notice: Требование или уведомление ГНК" in sent  # виды — из справочника
    assert model.bodies[0]["response_format"]["type"] == "json_schema"

    async with container.session_factory() as session:
        row = (await session.execute(select(AiSuggestion))).scalar_one()
    assert (row.function, row.alias, row.status, row.source, row.crm_user_id) == (
        "letter_intake",
        "intake-model",
        "ok",
        "text",
        4,
    )
    assert (row.input_tokens, row.output_tokens, str(row.cost_usd)) == (900, 120, "0.000400")
    assert row.prompt_version == body["prompt_version"] and len(row.prompt_version) == 12

    decided = await client.post(
        f"/api/v1/ai-suggestions/{body['suggestion_id']}/decision",
        json={"decision": "edited"},
        headers=staff["registrar"].headers,
    )
    assert decided.status_code == 204, decided.text
    other = await client.post(
        f"/api/v1/ai-suggestions/{body['suggestion_id']}/decision",
        json={"decision": "accepted"},
        headers=staff["director"].headers,
    )
    assert_error(other, 404, "NOT_FOUND")  # чужое предложение: решение пишет только тот, кто вызывал
    async with container.session_factory() as session:
        assert (await session.execute(select(AiSuggestion.decision))).scalar_one() == "edited"


async def test_code_decides_kind_and_dates(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel
) -> None:
    model.answer = {**ANSWER, "kind": "lottery", "sender_ref_date": "2099-01-01", "document_due": "завтра"}
    fields = (await intake(client, staff["registrar"], make_pdf(LETTER_LINES))).json()["fields"]
    assert (fields["kind"], fields["sender_ref_date"], fields["document_due"]) == (None, None, None)

    model.answer = dict.fromkeys(ANSWER)
    empty = await intake(client, staff["registrar"], make_pdf(["No INN here, just a long enough line of text."]))
    assert_error(empty, 409, "CONFLICT", reason="nothing_recognized")


async def test_until_the_first_policy_event_eds_is_strict(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, container: Container
) -> None:
    """События CRM ещё не было — EDS не открывает больше, чем выбрал админ: «Строгая», сканы не читаются."""
    shown = await client.get("/api/v1/docflow-settings", headers=staff["registrar"].headers)
    assert shown.json()["pii_policy"] == "strict"
    await intake(client, staff["registrar"], make_pdf([*LETTER_LINES, BUSINESS_PERSONAL]))
    sent = json.dumps(model.bodies[-1], ensure_ascii=False)
    for secret in ("301234567", "20208000900123456001", "+998 90 123 45 67", "AA1234567"):
        assert secret not in sent, secret
    scan = await intake(client, staff["registrar"], PNG, name="scan.png", content_type="image/png")
    assert_error(scan, 409, "CONFLICT", reason="scan_recognition_disabled")
    # Первое событие CRM (даже «Деловая») снимает ограничение; повтор того же события безвреден.
    assert await deliver_policy(client, container, "business") == "processed"
    assert await deliver_policy(client, container, "business") == "processed"
    ok = await intake(client, staff["registrar"], PNG, name="scan.png", content_type="image/png")
    assert ok.status_code == 200, ok.text


async def test_business_policy_masks_only_personal_ids_by_default(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, container: Container
) -> None:
    """«Деловая» (по умолчанию в CRM): реквизиты компании модель видит, паспорт, ПИНФЛ, карту и дату рождения — нет;
    номера из ответа код возвращает сам."""
    assert await deliver_policy(client, container, "business") == "processed"
    model.answer = {**ANSWER, "sender_ref_number": "1234567/KC"}
    lines = [*LETTER_LINES, BUSINESS_PERSONAL]
    body = (await intake(client, staff["registrar"], make_pdf(lines), name="letter.pdf")).json()
    sent = json.dumps(model.bodies[0], ensure_ascii=False)
    for kept in ("1234567/KC", "301234567", "20208000900123456001", "+998 90 123 45 67", "inspector@example.uz"):
        assert kept in sent, kept
    for hidden in ("AA1234567", "31234567890123", "4111 1111 1111 1111", "12.03.1985"):
        assert hidden not in sent, hidden
    assert "[passport]" in sent and "[date]" in sent
    assert body["fields"]["sender_inn"] == "301234567"
    assert body["fields"]["sender_ref_number"] == "1234567/KC"


async def test_policy_switch_changes_masking_without_restart(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, container: Container
) -> None:
    """Смена политики в CRM действует на следующий вызов того же процесса; старое событие её не откатывает."""
    pdf = make_pdf([*LETTER_LINES, BUSINESS_PERSONAL])
    assert await deliver_policy(client, container, "business", at="2026-11-03T08:00:00Z") == "processed"
    await intake(client, staff["registrar"], pdf)
    assert "301234567" in json.dumps(model.bodies[-1], ensure_ascii=False)

    assert await deliver_policy(client, container, "strict", at="2026-11-03T10:00:00Z") == "processed"
    await intake(client, staff["registrar"], pdf)
    strict = json.dumps(model.bodies[-1], ensure_ascii=False)
    for secret in ("301234567", "20208000900123456001", "+998 90 123 45 67", "inspector@example.uz", "AA1234567"):
        assert secret not in strict, secret

    # Опоздавшее событие («Деловая» в 09:00) строгую политику не отменяет; повтор — тоже.
    assert await deliver_policy(client, container, "business", at="2026-11-03T09:30:00Z") == "processed"
    await intake(client, staff["registrar"], pdf)
    assert "301234567" not in json.dumps(model.bodies[-1], ensure_ascii=False)

    assert await deliver_policy(client, container, "business", at="2026-11-03T11:00:00Z") == "processed"
    await intake(client, staff["registrar"], pdf)
    assert "301234567" in json.dumps(model.bodies[-1], ensure_ascii=False)
    async with container.session_factory() as session:
        journal = (await session.execute(select(JournalEntry.action))).scalars().all()
    assert journal.count("docflow_settings.pii_policy") == 3  # применены 08:00, 10:00 и 11:00; опоздавшее 09:30 — нет


async def test_scans_follow_the_policy_and_the_admin_switch(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, container: Container
) -> None:
    """Скан или фото: «Деловая» и включённая настройка (по умолчанию) — в модель; иначе понятный отказ."""
    assert await deliver_policy(client, container, "business", at="2026-11-03T08:00:00Z") == "processed"
    settings = await client.get("/api/v1/docflow-settings", headers=staff["registrar"].headers)
    validate("DocflowSettings", settings.json())
    assert settings.json() == {
        "recognize_scans": True,
        "pii_policy": "business",
        "ai_available": True,
        "author_may_sign_own_letter": True,
    }

    on = await intake(client, staff["registrar"], PNG, name="scan.png", content_type="image/png")
    assert on.status_code == 200, on.text
    assert on.json()["source"] == "image"
    assert on.json()["fields"]["sender_inn"] is None  # в скане код текста не видит — ИНН не угадываем
    content = model.bodies[0]["messages"][1]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    assert await deliver_policy(client, container, "strict") == "processed"
    strict = await intake(client, staff["registrar"], PNG, name="scan.png", content_type="image/png")
    body = assert_error(strict, 409, "CONFLICT", reason="scan_recognition_disabled")
    assert "строгой политике" in body["message"]
    assert len(model.bodies) == 1  # при «Строгой» в модель ничего не ушло
    shown = await client.get("/api/v1/docflow-settings", headers=staff["registrar"].headers)
    assert shown.json() == {
        "recognize_scans": True,
        "pii_policy": "strict",
        "ai_available": True,
        "author_may_sign_own_letter": True,
    }

    assert await deliver_policy(client, container, "business", at="2026-11-03T12:00:00Z") == "processed"
    denied = await client.patch(
        "/api/v1/docflow-settings", json={"recognize_scans": False}, headers=staff["registrar"].headers
    )
    assert_error(denied, 403, "FORBIDDEN", permission="bus.manage")
    turned = await client.patch(
        "/api/v1/docflow-settings", json={"recognize_scans": False}, headers=staff["admin"].headers
    )
    assert turned.json() == {
        "recognize_scans": False,
        "pii_policy": "business",
        "ai_available": True,
        "author_may_sign_own_letter": True,
    }
    off = await intake(client, staff["registrar"], PNG, name="scan.png", content_type="image/png")
    assert_error(off, 409, "CONFLICT", reason="scan_recognition_disabled")
    assert len(model.bodies) == 1

    again = await client.patch(
        "/api/v1/docflow-settings", json={"recognize_scans": True}, headers=staff["admin"].headers
    )
    assert again.json()["recognize_scans"] is True
    back = await intake(client, staff["registrar"], PNG, name="scan.png", content_type="image/png")
    assert back.status_code == 200, back.text


async def test_helper_off_or_out_of_budget_tells_to_fill_by_hand(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, settings: Settings,
    monkeypatch: pytest.MonkeyPatch, container: Container,
) -> None:  # fmt: skip
    model.status = 400
    budget = await intake(client, staff["registrar"], make_pdf(LETTER_LINES))
    assert_error(budget, 409, "CONFLICT", reason="ai_budget_exceeded")
    async with container.session_factory() as session:
        assert (await session.execute(select(AiSuggestion.status))).scalar_one() == "budget"

    monkeypatch.setattr(settings, "litellm_api_key", SecretStr(""))
    off = await intake(client, staff["registrar"], make_pdf(LETTER_LINES))
    assert_error(off, 409, "CONFLICT", reason="ai_unavailable")
    docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    docx = await intake(client, staff["registrar"], b"PK\x03\x04" + b"z" * 100, name="a.docx", content_type=docx_type)
    assert_error(docx, 422, "VALIDATION_FAILED")

    async with container.session_factory() as session:
        journal = (await session.execute(select(JournalEntry.action))).scalars().all()
    assert "docflow_settings.updated" not in journal


async def test_only_registrars_call_the_helper(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    for who in ("manager", "accountant"):
        response = await client.post(
            "/api/v1/letter-intake",
            json={"file_id": "00000000-0000-4000-8000-000000000001"},
            headers=staff[who].headers,
        )
        assert_error(response, 403, "FORBIDDEN", permission="letters.register")


async def test_key_sync_registers_budget_and_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path == "/key/info":
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"key": "sk-x"})

    monkeypatch.setattr(provision, "TRANSPORT", httpx.MockTransport(handler))
    assert await provision.sync_key("http://litellm:4000", "sk-master", "sk-eds", 1.5) == "created"
    _, path, body = calls[-1]
    assert path == "/key/generate"
    assert (body["key_alias"], body["max_budget"], body["budget_duration"]) == ("eds", 1.5, "1d")
    assert body["models"] == ["draft-model", "fallback-model", "intake-model"]  # план 1.4: помощник письма
    assert "sk-eds" not in calls[0][1]  # значение ключа не попадает в адрес


async def test_key_sync_attaches_langfuse_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli import ai_cli

    calls: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content) if request.content else {}))
        return httpx.Response(200, json={"info": {"key_alias": "eds"}} if request.url.path == "/key/info" else {})

    monkeypatch.setattr(provision, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setenv("EDS_LITELLM_API_KEY", "sk-eds")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    monkeypatch.setenv("EDS_LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("EDS_LANGFUSE_SECRET_KEY", "sk-lf-x")
    monkeypatch.delenv("EDS_LANGFUSE_HOST", raising=False)
    assert await ai_cli.run() == 0
    path, body = calls[-1]
    assert path == "/key/update"
    [callback] = body["metadata"]["logging"]
    assert callback["callback_name"] == "langfuse"
    assert callback["callback_vars"] == {
        "langfuse_public_key": "pk-lf-x",
        "langfuse_secret_key": "sk-lf-x",
        "langfuse_host": "http://langfuse-web:3000",
    }
    monkeypatch.delenv("EDS_LANGFUSE_SECRET_KEY")
    assert await ai_cli.run() == 0
    assert "logging" not in calls[-1][1]["metadata"]  # без ключей Langfuse — без колбэка


async def test_key_sync_cli_skips_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli import ai_cli

    monkeypatch.delenv("EDS_LITELLM_API_KEY", raising=False)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    assert await ai_cli.run() == 0  # стенд поднимается, помощник выключен


async def test_limits_are_checked_before_reading_the_file(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel
) -> None:
    big = make_pdf(LETTER_LINES) + b"%" * (letter_intake.MAX_PDF_BYTES + 1)
    too_big = await intake(client, staff["registrar"], big, name="big.pdf")
    assert_error(too_big, 409, "CONFLICT", reason="file_too_large")
    pages = await intake(client, staff["registrar"], make_pdf(LETTER_LINES, pages=letter_intake.MAX_PDF_PAGES + 1))
    assert_error(pages, 409, "CONFLICT", reason="file_too_large")
    assert model.bodies == []  # в модель ничего не ушло


async def test_zero_budget_means_no_limit(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    assert (await intake(client, staff["registrar"], make_pdf(LETTER_LINES))).status_code == 200  # потрачено 0.0004
    monkeypatch.setattr(settings, "ai_daily_budget_usd", 0.0004)
    spent = await intake(client, staff["registrar"], make_pdf(LETTER_LINES))
    assert_error(spent, 409, "CONFLICT", reason="ai_budget_exceeded")
    monkeypatch.setattr(settings, "ai_daily_budget_usd", 0.0)
    assert (await intake(client, staff["registrar"], make_pdf(LETTER_LINES))).status_code == 200


def test_document_due_must_be_in_a_sane_range() -> None:
    from datetime import date

    today = date(2026, 11, 3)
    far = letter_intake.clean({**ANSWER, "document_due": "2099-01-01"}, masked=None, kinds=set(), raw="", today=today)
    old = letter_intake.clean({**ANSWER, "document_due": "2020-01-01"}, masked=None, kinds=set(), raw="", today=today)
    ok = letter_intake.clean({**ANSWER, "document_due": "2026-11-10"}, masked=None, kinds=set(), raw="", today=today)
    assert (far.document_due, old.document_due, str(ok.document_due)) == (None, None, "2026-11-10")


async def test_key_sync_cli_survives_an_unreachable_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli import ai_cli

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(provision, "TRANSPORT", httpx.MockTransport(down))
    monkeypatch.setenv("EDS_LITELLM_API_KEY", "sk-eds")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    assert await ai_cli.run() == 0  # стенд поднимается, помощник выключен


def test_relative_due_in_the_letter_text_is_suggested_by_code() -> None:
    """СЦ-11: «в течение 5 рабочих дней» без даты — срок считает код (пн–пт), модель его не называет."""
    from datetime import date

    from app.services.letter_intake import due_from_text

    friday = date(2026, 11, 20)
    assert due_from_text("Просим представить пояснения в течение 5 рабочих дней с даты получения.", friday) == date(
        2026, 11, 27
    )
    assert due_from_text("в течение 5 (пяти) рабочих дней", friday) == date(2026, 11, 27)
    assert due_from_text("в течение 10 календарных дней", friday) == date(2026, 11, 30)
    assert due_from_text("в течение 3 дней", friday) == date(2026, 11, 23)
    assert due_from_text("5 ish kuni ichida", friday) == date(2026, 11, 27)
    assert due_from_text("Срок не указан", friday) is None
    assert due_from_text("в течение 500 дней", friday) is None
    # срок из текста подставляется в предложение; названный моделью датой — главнее
    today = date(2026, 11, 20)
    guessed = letter_intake.clean(
        {**ANSWER, "document_due": None}, masked=None, kinds=set(), raw="в течение 5 рабочих дней", today=today
    )
    assert guessed.document_due == date(2026, 11, 27)
    explicit = letter_intake.clean(
        {**ANSWER, "document_due": "2026-11-25"}, masked=None, kinds=set(), raw="в течение 5 рабочих дней", today=today
    )
    assert explicit.document_due == date(2026, 11, 25)


async def test_due_from_the_text_is_suggested_without_the_model(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, settings: Settings,
    monkeypatch: pytest.MonkeyPatch, container: Container,
) -> None:  # fmt: skip
    """СЦ-11: срок «N ish kuni ichida» считает код — при выключенной модели и при её сбое он всё равно предложен."""
    lines = [
        "Tax Committee of Demo District",
        "Explanations are due 5 ish kuni ichida from receipt of this notice.",
        *LETTER_LINES[:1],
    ]
    monkeypatch.setattr(settings, "litellm_api_key", SecretStr(""))
    off = await intake(client, staff["registrar"], make_pdf(lines))
    assert off.status_code == 200, off.text
    body = off.json()
    validate("LetterIntakeSuggestion", body)
    assert (body["alias"], body["source"]) == ("rules", "text")
    assert body["fields"]["document_due"] is not None
    assert model.bodies == []  # платного вызова не было

    monkeypatch.setattr(settings, "litellm_api_key", SecretStr("sk-test-eds-key"))
    model.status = 500
    down = await intake(client, staff["registrar"], make_pdf(lines))
    assert down.status_code == 200, down.text
    assert down.json()["alias"] == "rules" and down.json()["fields"]["document_due"] == body["fields"]["document_due"]
    # дата поступления из формы — точка отсчёта срока (5 рабочих дней от субботы 2026-01-10 — пятница 16-го)
    dated = await intake(client, staff["registrar"], make_pdf(lines), received_at="2026-01-10")
    assert dated.status_code == 200 and dated.json()["fields"]["document_due"] == "2026-01-16"
    # текст без срока по-прежнему отправляет заполнять вручную
    plain = await intake(client, staff["registrar"], make_pdf(LETTER_LINES))
    assert_error(plain, 409, "CONFLICT", reason="ai_budget_exceeded")


_WORDS = [
    "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "одиннадцать",
    "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать",
    "девятнадцать", "двадцать", "двадцать один", "двадцать два", "двадцать три", "двадцать четыре",
    "двадцать пять", "двадцать шесть", "двадцать семь", "двадцать восемь", "двадцать девять", "тридцать",
]  # fmt: skip
_GENITIVE = [
    "одного", "двух", "трёх", "четырёх", "пяти", "шести", "семи", "восьми", "девяти", "десяти", "одиннадцати",
    "двенадцати", "тринадцати", "четырнадцати", "пятнадцати", "шестнадцати", "семнадцати", "восемнадцати",
    "девятнадцати", "двадцати", "двадцати одного", "двадцати двух", "двадцати трёх", "двадцати четырёх",
    "двадцати пяти", "двадцати шести", "двадцати семи", "двадцати восьми", "двадцати девяти", "тридцати",
]  # fmt: skip
FRIDAY = date(2026, 11, 20)


def _after(days: int, *, working: bool = False) -> date:
    """Ожидание независимо от кода: рабочие дни идут по одному, календарный срок с выходного — на понедельник."""
    day = FRIDAY
    if working:
        while days:
            day += timedelta(days=1)
            days -= day.weekday() < 5
        return day
    day += timedelta(days=days)
    return day + timedelta(days=(7 - day.weekday()) % 7 if day.weekday() >= 5 else 0)


@pytest.mark.parametrize("n", range(1, 31))
@pytest.mark.parametrize("kind", ["календарных", "рабочих"])
def test_due_numerals_1_to_30_in_every_form(n: int, kind: str) -> None:
    """СЦ-11: числа 1–30 цифрами, «5-ти», словом в именительном и родительном падеже, «(…)» после цифры."""
    working = kind == "рабочих"
    expected = _after(n, working=working)
    forms = [f"{n}", f"{n}-ти", f"{_WORDS[n - 1]}", f"{_GENITIVE[n - 1]}", f"{n} ({_GENITIVE[n - 1]})"]
    for form in forms:
        text = f"Просим ответить в течение {form} {kind} дней с даты получения."
        assert letter_intake.due_from_text(text, FRIDAY) == expected, text


def test_due_numerals_outside_the_table_give_no_suggestion() -> None:
    assert letter_intake.due_from_text("в течение сорока дней", FRIDAY) is None
    assert letter_intake.due_from_text("в течение пять пять дней", FRIDAY) is None  # не число
    assert letter_intake.due_from_text("в течение 95 дней", FRIDAY) is None


def test_due_is_counted_from_the_receipt_date_when_there_is_one() -> None:
    """СЦ-11: срок отсчитывается от даты поступления письма, а без неё — от дня регистрации."""
    today, received = date(2026, 11, 25), date(2026, 11, 20)  # письмо пришло в пятницу, регистрируют в среду
    raw = "в течение 5 рабочих дней"
    with_received = letter_intake.rules_fields(raw, today, base=received)
    without = letter_intake.rules_fields(raw, today)
    assert with_received is not None and without is not None
    assert with_received.document_due == date(2026, 11, 27)
    assert without.document_due == date(2026, 12, 2)
    cleaned = letter_intake.clean({}, masked=None, kinds=set(), raw=raw, today=today, base=received)
    assert cleaned.document_due == date(2026, 11, 27)


@pytest.mark.parametrize("failure", ["500", "timeout", "junk"])
async def test_real_model_failure_still_gives_the_due_date_by_rules(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, failure: str
) -> None:
    """СЦ-11: сбой модели (500 без лимита, тишина, не-JSON) — не «заполните вручную», а срок по тексту от кода."""
    model.failure = failure
    lines = ["Tax Committee of Demo District", "Explanations are due 5 ish kuni ichida from receipt of this notice."]
    response = await intake(client, staff["registrar"], make_pdf(lines))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["alias"] == "rules" and body["by_code"] == ["document_due"]
    assert model.bodies  # модель звали, она не ответила


async def test_by_code_marks_what_the_code_computed_next_to_the_model_answer(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel
) -> None:
    """СЦ-11: модель срок не назвала датой — срок и ИНН помечены `by_code`, остальное остаётся за моделью."""
    model.answer = {**ANSWER, "document_due": None}
    lines = ["Tax Committee of Demo District", "To: Demo Rail LLC, INN 301234567", "Reply 5 ish kuni ichida please"]
    mixed = await intake(client, staff["registrar"], make_pdf(lines))
    body = mixed.json()
    assert body["alias"] == "intake-model"
    assert body["fields"]["subject"] and body["fields"]["document_due"]
    assert sorted(body["by_code"]) == ["document_due", "sender_inn"]
    model.answer = ANSWER  # модель сама назвала дату срока — срок её, ИНН по-прежнему кода
    named = await intake(client, staff["registrar"], make_pdf(lines))
    assert named.json()["by_code"] == ["sender_inn"]


@pytest.mark.parametrize("received", ["2999-01-01", "9999-12-31", "2001-01-01"])
async def test_receipt_date_out_of_range_is_rejected(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, received: str
) -> None:
    """СЦ-11: дата поступления из будущего, у предела календаря (раньше — 500) или старше года — 422, а не расчёт."""
    lines = ["Tax Committee", "Reply 5 ish kuni ichida please"]
    response = await intake(client, staff["registrar"], make_pdf(lines), received_at=received)
    assert_error(response, 422, "VALIDATION_FAILED")
    assert "received_at" in json.dumps(response.json()["details"])
    assert model.bodies == []


def test_due_at_the_calendar_edge_is_no_suggestion_not_a_crash() -> None:
    assert letter_intake.due_from_text("в течение 5 дней", date(9999, 12, 31)) is None


UZ_DUE = ["Tax Committee", "Reply 5 ish kuni ichida please"]


async def test_recompute_by_rules_never_calls_the_model(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel
) -> None:
    """СЦ-11: «Пересчитать срок» — только правила кода: модель не зовётся, срок помечен `by_code`; без срока — 409."""
    done = await intake(client, staff["registrar"], make_pdf(UZ_DUE), received_at="2026-10-20", rules_only=True)
    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["alias"], body["by_code"]) == ("rules", ["document_due"])
    assert body["fields"]["document_due"] == "2026-10-27"
    nothing = await intake(client, staff["registrar"], make_pdf(LETTER_LINES), rules_only=True)
    assert_error(nothing, 409, "CONFLICT", reason="nothing_recognized")
    assert model.bodies == []


@pytest.mark.parametrize(
    ("received", "status", "reason"),
    [
        ("2026-11-25", 200, None),  # день компании: в Ташкенте уже 25-е, хотя в UTC ещё 24-е
        ("2026-11-26", 422, "in_future"),
        ("2025-11-25", 200, None),  # ровно год назад
        ("2025-11-24", 422, "too_old"),
    ],
)
async def test_receipt_date_boundaries_follow_the_company_day(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, clock: Any,
    received: str, status: int, reason: str | None,
) -> None:  # fmt: skip
    """СЦ-11: 20:30 UTC 24.11 — в Ташкенте 01:30 25.11; границы окна считаются по дню компании, не по UTC."""
    clock.current = datetime(2026, 11, 24, 20, 30, tzinfo=UTC)
    response = await intake(client, staff["registrar"], make_pdf(UZ_DUE), received_at=received)
    assert response.status_code == status, response.text
    if reason is not None:
        assert [f["message"] for f in response.json()["details"]["fields"]] == [reason]
