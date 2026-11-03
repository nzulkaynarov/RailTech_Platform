"""EDS · «Зарегистрировать входящее» (P8, SPEC-v3 §3.2a п. 1): раздел `eds.inbox.register`,
тело EDS, справочник видов, проверка дубля; делопроизводитель без резолюции. EDS — на respx.
"""

import json
from typing import Any

import httpx
import pytest

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import FILE_ID, LETTER_ID, EdsFake, eds_error_body, letter
from tests.roles import Role

BASE = "/api/v1/eds"
FORM: dict[str, Any] = {
    "kind": "tax_notice",
    "receipt_method": "taxpayer_cabinet",
    "sender_name": " ГНИ Мирабадского района ",
    "received_at": "2026-10-29",
    "subject": "Требование о пояснениях по НДС",
    "summary": "  ",
    "sender_ref_number": "04-12/3456",
    "sender_ref_date": "2026-10-28",
    "signed_by": "А. Каримов",
    "document_due": "2026-11-05",
    "urgent": False,
    "related_number": None,
    "file_ids": [FILE_ID],
}
KINDS = {
    "items": [
        {
            "code": "tax_notice",
            "name": {"ru": "Требование или уведомление ГНК", "uz": "Talabnoma", "en": "Tax notice"},
            "urgent": True,
            "due_days": 3,
        },
        {
            "code": "other",
            "name": {"ru": "Прочее", "uz": "Boshqa", "en": "Other"},
            "urgent": False,
            "due_days": None,
        },
    ]
}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    registered = letter(
        links={},
        urgent=True,
        kind="tax_notice",
        receipt_method="taxpayer_cabinet",
        signed_by="А. Каримов",
        document_due="2026-11-05",
        related={"kind": "letter_in", "id": LETTER_ID, "number": "ВХ-101/26"},
    )
    fake.answer("POST", "letters", httpx.Response(201, json=registered))
    fake.answer("GET", "letter-kinds", httpx.Response(200, json=KINDS))
    return fake


async def test_registrar_registers_and_gets_the_card(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.client.post(
        f"{BASE}/letters",
        json=FORM,
        headers={CSRF_HEADER: web.csrf, "Idempotency-Key": "form-key-1"},
    )

    check(response, "/eds/letters", "post")
    assert response.status_code == 201, response.text
    card = response.json()
    assert (card["status"], card["kind"], card["receipt_method"]) == (
        "awaiting_resolution",
        "tax_notice",
        "taxpayer_cabinet",
    )
    assert card["related"] == {
        "kind": "letter_in",
        "number": "ВХ-101/26",
        "path": "/eds/inbox/%D0%92%D0%A5-101%2F26",
    }
    [call] = eds.made("POST", "letters")
    assert call.headers["idempotency-key"] == "form-key-1"
    assert json.loads(call.content) == {
        "kind": "tax_notice",
        "receipt_method": "taxpayer_cabinet",
        "subject": "Требование о пояснениях по НДС",
        "sender": {"name": "ГНИ Мирабадского района", "inn": None},
        "received_at": "2026-10-29",
        "urgent": False,
        "file_ids": [FILE_ID],
        "signed_by": "А. Каримов",
        "document_due": "2026-11-05",
        "related_number": None,
        "sender_ref": {"number": "04-12/3456", "date": "2026-10-28"},
    }


async def test_links_to_a_request_and_a_client_go_to_eds_links(web: Web, eds: EdsFake) -> None:
    assert (await web.login(["DIRECTOR"])).status_code == 200
    body = {**FORM, "erp_deal_id": 5, "deal_number": "ЗВ-2026-104", "crm_client_id": 42}
    body["summary"] = "Пояснить расхождение"

    response = await web.send("POST", f"{BASE}/letters", json=body)
    assert response.status_code == 201, response.text

    [call] = eds.made("POST", "letters")
    sent = json.loads(call.content)
    assert sent["links"] == {"erp_deal_id": 5, "deal_number": "ЗВ-2026-104", "crm_client_id": 42}
    assert sent["summary"] == "Пояснить расхождение"


@pytest.mark.parametrize("roles", [["MANAGER_ALL"], ["MANAGER"], ["ACCOUNTANT"], ["ADMIN"]])
async def test_only_the_register_section_registers(
    web: Web, eds: EdsFake, roles: list[Role]
) -> None:
    assert (await web.login(roles)).status_code == 200

    response = await web.send("POST", f"{BASE}/letters", json=FORM)

    assert response.status_code == 403
    assert response.json()["details"]["resource"] == "eds.inbox.register"
    assert eds.made("POST", "letters") == []


async def test_registrar_reads_the_inbox_but_cannot_resolve(web: Web, eds: EdsFake) -> None:
    """SPEC-v3 §3.2a «Права»: «регистрировать входящие» ≠ «резолюция»."""
    assert (await web.login(["REGISTRAR"])).status_code == 200

    assert (await web.client.get(f"{BASE}/letters")).status_code == 200
    assert (await web.client.get(f"{BASE}/letters/{LETTER_ID}")).status_code == 200
    for action, body in (
        ("resolution", {}),
        ("return", {"comment": "x"}),
        ("reject", {"reason": "x"}),
    ):
        denied = await web.send("POST", f"{BASE}/letters/{LETTER_ID}/{action}", json=body)
        assert denied.status_code == 403, action
        assert denied.json()["details"]["resource"] == "eds.inbox"
    assert (await web.client.get(f"{BASE}/resolution/assignees")).status_code == 403


@pytest.mark.parametrize(
    "patch",
    [
        {"file_ids": []},
        {"kind": "Налоговая"},
        {"receipt_method": "Голубь"},
        {"sender_name": "  "},
        {"subject": ""},
        {"received_at": None},
    ],
)
async def test_form_errors_are_422_without_calling_eds(
    web: Web, eds: EdsFake, patch: dict[str, Any]
) -> None:
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.send("POST", f"{BASE}/letters", json={**FORM, **patch})

    assert response.status_code == 422
    assert eds.made("POST", "letters") == []


async def test_eds_422_related_number_is_passed_with_the_field(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "POST",
        "letters",
        httpx.Response(
            422,
            json=eds_error_body(
                "VALIDATION_FAILED",
                "Документ с таким номером не найден.",
                fields=[{"field": "related_number", "message": "not_found", "type": "value_error"}],
            ),
        ),
    )
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.send("POST", f"{BASE}/letters", json={**FORM, "related_number": "ВХ-9/26"})

    assert response.status_code == 422
    details = response.json()["details"]
    assert (details["fields"], details["reason"]) == (["related_number"], "not_found")


async def test_letter_kinds_for_readers_and_registrars(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    for code in ("REGISTRAR", "MANAGER_ALL", "DIRECTOR"):
        assert (await web.login([code])).status_code == 200
        response = await web.client.get(f"{BASE}/letter-kinds")
        check(response, "/eds/letter-kinds", "get")
        assert response.json() == KINDS
    assert (await web.login(["SUPPLY"])).status_code == 200
    assert (await web.client.get(f"{BASE}/letter-kinds")).status_code == 403


async def test_duplicates_pass_the_check_and_link_to_the_letter(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    found = {
        "items": [
            {
                "id": LETTER_ID,
                "number": "ВХ-104/26",
                "subject": "Требование",
                "received_at": "2026-10-24",
                "status": "awaiting_resolution",
            }
        ]
    }
    eds.answer("GET", "letter-duplicates", httpx.Response(200, json=found))
    assert (await web.login(["REGISTRAR"])).status_code == 200

    response = await web.client.get(
        f"{BASE}/letter-duplicates",
        params={"ref_number": " 04-12/3456 ", "sender_name": " ГНИ ", "crm_client_id": 42},
    )

    check(response, "/eds/letter-duplicates", "get")
    assert response.json()["items"][0]["path"] == "/eds/inbox/%D0%92%D0%A5-104%2F26"
    [call] = eds.made("GET", "letter-duplicates")
    assert dict(call.url.params) == {
        "ref_number": "04-12/3456",
        "sender_name": "ГНИ",
        "crm_client_id": "42",
    }
