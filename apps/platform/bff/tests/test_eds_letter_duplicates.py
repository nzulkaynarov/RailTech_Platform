"""EDS · одно письмо — один входящий номер (EDS-DUP): фоновая проверка формы, 409
`duplicate_letter` с найденным ВХ и ссылкой, «зарегистрировать всё равно» с причиной,
«Это дубль ВХ-…» и права. EDS — на respx."""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import FILE_ID, LETTER_ID, EdsFake, eds_error_body, letter
from tests.test_eds_letter_registration import BASE, FORM

FOUND: dict[str, Any] = {
    "id": LETTER_ID,
    "number": "ВХ-104/26",
    "subject": "Требование о пояснениях по НДС",
    "received_at": "2026-10-29",
    "status": "in_execution",
    "registered_at": "2026-10-29T09:00:00Z",
    "match": "exact",
}
PATH = "/eds/inbox/%D0%92%D0%A5-104%2F26"


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    return EdsFake(be)


async def test_background_check_sends_form_fields_and_returns_matches_with_links(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    similar = {**FOUND, "id": FILE_ID, "number": "ВХ-099/26", "match": "same_subject"}
    eds.answer(
        "POST", "letters/duplicates-check", httpx.Response(200, json={"items": [FOUND, similar]})
    )
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.send(
        "POST",
        f"{BASE}/letters/duplicates-check",
        json={
            "sender_name": " ГНИ  ",
            "sender_inn": "301234567",
            "sender_ref_number": " 04-12/3456 ",
            "sender_ref_date": "2026-10-28",
            "subject": "Требование",
            "received_at": "2026-10-29",
            "file_ids": [FILE_ID],
        },
    )

    check(response, "/eds/letters/duplicates-check", "post")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [(i["number"], i["match"], i["path"]) for i in items] == [
        ("ВХ-104/26", "exact", PATH),
        ("ВХ-099/26", "same_subject", "/eds/inbox/%D0%92%D0%A5-099%2F26"),
    ]
    [call] = eds.made("POST", "letters/duplicates-check")
    assert json.loads(call.content) == {
        "sender": {"name": "ГНИ", "inn": "301234567"},
        "crm_client_id": None,
        "sender_ref": {"number": "04-12/3456", "date": "2026-10-28"},
        "subject": "Требование",
        "received_at": "2026-10-29",
        "file_ids": [FILE_ID],
    }


async def test_check_needs_inbox_reading_or_registering(web: Web, eds: EdsFake) -> None:
    eds.answer("POST", "letters/duplicates-check", httpx.Response(200, json={"items": []}))
    for code in ("REGISTRAR", "MANAGER_ALL", "DIRECTOR"):
        assert (await web.login([code])).status_code == 200
        assert (
            await web.send("POST", f"{BASE}/letters/duplicates-check", json={})
        ).status_code == 200
    assert (await web.login(["SUPPLY"])).status_code == 200
    assert (await web.send("POST", f"{BASE}/letters/duplicates-check", json={})).status_code == 403


async def test_exact_duplicate_409_carries_the_found_letter_and_force_goes_to_eds(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    conflict = eds_error_body(
        "CONFLICT",
        "Это письмо уже зарегистрировано: ВХ-104/26.",
        reason="duplicate_letter",
        duplicate=FOUND,
    )
    eds.answer("POST", "letters", httpx.Response(409, json=conflict))
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.send("POST", f"{BASE}/letters", json=FORM)

    check(response, "/eds/letters", "post")
    assert response.status_code == 409
    body = response.json()
    assert body["message"] == "Это письмо уже зарегистрировано: ВХ-104/26."
    assert body["details"]["reason"] == "duplicate_letter"
    assert body["details"]["duplicate"] == {**FOUND, "path": PATH}

    eds.answer("POST", "letters", httpx.Response(201, json=letter()))
    forced = await web.send(
        "POST",
        f"{BASE}/letters",
        json={**FORM, "force": True, "force_reason": "  Повторное письмо  "},
    )
    assert forced.status_code == 201, forced.text
    sent = json.loads(eds.made("POST", "letters")[-1].content)
    assert (sent["force"], sent["force_reason"]) == (True, "Повторное письмо")
    assert "force" not in json.loads(eds.made("POST", "letters")[0].content)


async def test_mark_duplicate_goes_to_eds_and_returns_the_card(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    closed = letter(status="duplicate", duplicate_of={"id": FILE_ID, "number": "ВХ-099/26"})
    eds.answer("POST", f"letters/{LETTER_ID}/duplicate", httpx.Response(200, json=closed))
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.send(
        "POST",
        f"{BASE}/letters/{LETTER_ID}/duplicate",
        json={"original_number": "ВХ-099/26", "comment": " ", "confirm": True},
    )

    check(response, "/eds/letters/{id}/duplicate", "post")
    assert response.status_code == 200, response.text
    card = response.json()
    assert card["status"] == "duplicate"
    assert card["duplicate_of"] == {
        "number": "ВХ-099/26",
        "path": "/eds/inbox/%D0%92%D0%A5-099%2F26",
    }
    [call] = eds.made("POST", f"letters/{LETTER_ID}/duplicate")
    assert json.loads(call.content) == {
        "original_number": "ВХ-099/26",
        "comment": None,
        "confirm": True,
    }


async def test_mark_duplicate_resolution_exists_passes_status_and_count(
    web: Web, eds: EdsFake
) -> None:
    body = eds_error_body(
        "CONFLICT",
        "Подтвердите отмену поручений.",
        reason="resolution_exists",
        status="in_execution",
        instructions=2,
    )
    eds.answer("POST", f"letters/{LETTER_ID}/duplicate", httpx.Response(409, json=body))
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.send(
        "POST", f"{BASE}/letters/{LETTER_ID}/duplicate", json={"original_number": "ВХ-099/26"}
    )

    assert response.status_code == 409
    details = response.json()["details"]
    assert (details["reason"], details["status"], details["instructions"]) == (
        "resolution_exists",
        "in_execution",
        2,
    )


async def test_only_the_register_section_marks_duplicates(web: Web, eds: EdsFake) -> None:
    for code in ("MANAGER_ALL", "SUPPLY"):
        assert (await web.login([code])).status_code == 200
        denied = await web.send(
            "POST", f"{BASE}/letters/{LETTER_ID}/duplicate", json={"original_number": "ВХ-099/26"}
        )
        assert denied.status_code == 403
    assert eds.made("POST", f"letters/{LETTER_ID}/duplicate") == []
