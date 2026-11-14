"""EDS · «Заполнить из файла» и настройки документооборота (EDS-REG).

Разделы каталога, тела и ответы EDS как есть, отказ EDS с причиной. EDS — на respx;
BFF модели не зовёт.
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import FILE_ID, EdsFake, eds_error_body
from tests.roles import custom

BASE = "/api/v1/eds"
SUGGESTION_ID = "8a6f3c9e-1d2b-4c5d-9e8f-0a1b2c3d4e5f"
SUGGESTION: dict[str, Any] = {
    "suggestion_id": SUGGESTION_ID,
    "source": "text",
    "fields": {
        "sender_name": "ГНИ Демо-района",
        "sender_inn": "301234567",
        "sender_ref_number": "04-12/3456",
        "sender_ref_date": "2026-10-28",
        "subject": "Пояснения по НДС",
        "summary": "Просят пояснить расхождение до 10 ноября.",
        "kind": "tax_notice",
        "document_due": "2026-11-10",
    },
    "alias": "intake-model",
    "prompt_version": "0123456789ab",
}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    fake.answer("POST", "letter-intake", httpx.Response(200, json=SUGGESTION))
    fake.answer("POST", f"ai-suggestions/{SUGGESTION_ID}/decision", httpx.Response(204))
    settings = {"recognize_scans": False, "pii_policy": "business", "ai_available": True}
    fake.answer("GET", "docflow-settings", httpx.Response(200, json=settings))
    fake.answer(
        "PATCH", "docflow-settings", httpx.Response(200, json={**settings, "recognize_scans": True})
    )
    return fake


async def test_registrar_gets_suggestion_and_records_decision(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["REGISTRAR"])).status_code == 200
    response = await web.send("POST", f"{BASE}/letter-intake", json={"file_id": FILE_ID})
    check(response, "/eds/letter-intake", "post")
    assert response.json()["fields"]["kind"] == "tax_notice"
    [sent] = eds.made("POST", "letter-intake")
    assert sent.read() == f'{{"file_id":"{FILE_ID}"}}'.encode()
    decided = await web.send(
        "POST", f"{BASE}/ai-suggestions/{SUGGESTION_ID}/decision", json={"decision": "edited"}
    )
    assert decided.status_code == 204
    assert (
        await web.send("POST", f"{BASE}/letter-intake", json={"file_id": "x"})
    ).status_code == 422


async def test_eds_refusal_keeps_reason_and_text(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "POST",
        "letter-intake",
        httpx.Response(
            409,
            json=eds_error_body(
                "CONFLICT",
                "Распознавание сканов выключено — заполните вручную или включите в настройках.",
                reason="scan_recognition_disabled",
            ),
        ),
    )
    assert (await web.login(["REGISTRAR"])).status_code == 200
    response = await web.send("POST", f"{BASE}/letter-intake", json={"file_id": FILE_ID})
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "scan_recognition_disabled"


async def test_settings_read_by_registrar_and_admin_changed_by_admin(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["REGISTRAR"])).status_code == 200
    read = await web.client.get(f"{BASE}/docflow-settings")
    check(read, "/eds/docflow-settings", "get")
    denied = await web.send("PATCH", f"{BASE}/docflow-settings", json={"recognize_scans": True})
    assert denied.status_code == 403
    assert (await web.login(["ADMIN"])).status_code == 200
    changed = await web.send("PATCH", f"{BASE}/docflow-settings", json={"recognize_scans": True})
    check(changed, "/eds/docflow-settings", "patch")
    assert changed.json()["recognize_scans"] is True


async def test_others_cannot_call_the_helper(web: Web, eds: EdsFake) -> None:
    for code in ("MANAGER_ALL", "SUPPLY"):
        assert (await web.login([code])).status_code == 200
        response = await web.send("POST", f"{BASE}/letter-intake", json={"file_id": FILE_ID})
        assert response.status_code == 403
    assert eds.made("POST", "letter-intake") == []


async def test_helper_waits_for_the_model_longer_than_the_default_timeout(
    web: Web, eds: EdsFake
) -> None:
    """Модель отвечает до `EDS_AI_TIMEOUT_S` (60 с): общий таймаут бэкенда (3 с) её оборвал бы."""
    from app.api.eds_letter_intake import INTAKE_WAIT_SECONDS

    waits: list[float] = []

    def answer(request: httpx.Request) -> httpx.Response:
        waits.append(request.extensions["timeout"]["read"])
        return httpx.Response(200, json=SUGGESTION)

    eds.answer("POST", "letter-intake", answer)
    assert (await web.login(["REGISTRAR"])).status_code == 200
    response = await web.send("POST", f"{BASE}/letter-intake", json={"file_id": FILE_ID})
    assert response.status_code == 200
    assert waits == [INTAKE_WAIT_SECONDS]
    assert INTAKE_WAIT_SECONDS >= 80 + 5  # предел EDS_AI_TIMEOUT_S и запас на файл
    # обычные вызовы EDS — с общим таймаутом
    await web.client.get(f"{BASE}/docflow-settings")
    settings_call = eds.made("GET", "docflow-settings")[-1]
    assert settings_call.extensions["timeout"]["read"] < INTAKE_WAIT_SECONDS


# --- план 1.4: помощник письма -------------------------------------------------------------------

BODY = {
    "version": 1,
    "lang": "en",
    "doc": {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Please confirm."}]}
        ],
    },
}


async def test_author_gets_a_translation_with_back_translation(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    eds.answer(
        "POST",
        "letter-assist",
        httpx.Response(
            200,
            json={
                "suggestion_id": SUGGESTION_ID,
                "body": BODY,
                "back_translation": "Просим подтвердить.",
                "alias": "draft-model",
                "prompt_version": "0123456789ab",
            },
        ),
    )
    assert (await web.login(["MANAGER"])).status_code == 200
    source = {**BODY, "lang": "ru"}
    response = await web.send(
        "POST", f"{BASE}/letter-assist", json={"action": "translate", "lang": "en", "body": source}
    )
    assert response.status_code == 200, response.text
    check(response, "/eds/letter-assist", "post")
    assert response.json()["back_translation"] == "Просим подтвердить."
    assert "alias" not in response.json()
    [sent] = eds.made("POST", "letter-assist")
    assert json.loads(sent.read()) == {"action": "translate", "lang": "en", "body": source}


async def test_assist_needs_the_author_section(web: Web, eds: EdsFake) -> None:
    assert (
        await web.login([custom(77, "Без документов", {"dashboard.queue": "full"})])
    ).status_code == 200
    response = await web.send(
        "POST", f"{BASE}/letter-assist", json={"action": "draft", "lang": "ru", "brief": "x"}
    )
    assert response.status_code == 403
    assert eds.made("POST", "letter-assist") == []
