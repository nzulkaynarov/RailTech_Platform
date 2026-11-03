"""«Заполнить из файла» (EDS-REG, PD-BIZ, pg): PDF с текстом — в модель уходит маскированный текст по политике защиты
данных («Деловая» по умолчанию, «Строгая» — прежнее поведение; политика приходит событием CRM и действует сразу, без
перезапуска), номера возвращает код; скан — при «Деловой» и включённом «Распознавать сканы», при «Строгой» отказ; вид —
из справочника; ИНН — из текста кодом; журнал без текстов; настройки — у администратора. Модель — подмена транспорта
(`httpx.MockTransport`), платных вызовов нет."""

import json
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

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
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


async def intake(client: httpx.AsyncClient, who: Person, content: bytes, **kw: Any) -> httpx.Response:
    uploaded = await upload(client, who, content, **kw)
    assert uploaded.status_code == 201, uploaded.text
    return await client.post("/api/v1/letter-intake", json={"file_id": uploaded.json()["id"]}, headers=who.headers)


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


async def test_business_policy_masks_only_personal_ids_by_default(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, container: Container
) -> None:
    """«Деловая» (по умолчанию, события CRM ещё не было): реквизиты компании модель видит, паспорт, ПИНФЛ, карту и дату
    рождения — нет; номера из ответа код возвращает сам."""
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
    assert journal.count("docflow_settings.pii_policy") == 2  # применены 10:00 и 11:00; опоздавшее — нет


async def test_scans_follow_the_policy_and_the_admin_switch(
    client: httpx.AsyncClient, staff: dict[str, Person], model: FakeModel, container: Container
) -> None:
    """Скан или фото: «Деловая» и включённая настройка (по умолчанию) — в модель; иначе понятный отказ."""
    settings = await client.get("/api/v1/docflow-settings", headers=staff["registrar"].headers)
    validate("DocflowSettings", settings.json())
    assert settings.json() == {"recognize_scans": True, "pii_policy": "business", "ai_available": True}

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
    assert shown.json() == {"recognize_scans": True, "pii_policy": "strict", "ai_available": True}

    assert await deliver_policy(client, container, "business", at="2026-11-03T12:00:00Z") == "processed"
    denied = await client.patch(
        "/api/v1/docflow-settings", json={"recognize_scans": False}, headers=staff["registrar"].headers
    )
    assert_error(denied, 403, "FORBIDDEN", permission="bus.manage")
    turned = await client.patch(
        "/api/v1/docflow-settings", json={"recognize_scans": False}, headers=staff["admin"].headers
    )
    assert turned.json() == {"recognize_scans": False, "pii_policy": "business", "ai_available": True}
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
    assert body["models"] == ["fallback-model", "intake-model"]
    assert "sk-eds" not in calls[0][1]  # значение ключа не попадает в адрес


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
