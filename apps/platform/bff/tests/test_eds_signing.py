"""EDS · Права подписи (SIGN-2, ADR-0024): раздел `eds.signing.manage`, перевод форм и ответов,
ошибки EDS как есть, файл основания потоком. EDS — на respx."""

import json
from typing import Any

import httpx
import pytest

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import EdsFake, eds_error_body

BASE = "/api/v1/eds/signing"
AUTHORITY_ID = "5a7c1d2e-3f40-4b51-8c62-7d8e9f0a1b2c"
BOUNDARY = "sign-test-boundary"
HOLDER = {"crm_user_id": 5, "full_name": "Алия Каримова"}
ADMIN = {"crm_user_id": 9, "full_name": "Админ Админов"}
EDS_AUTHORITY: dict[str, Any] = {
    "id": AUTHORITY_ID,
    "holder": HOLDER,
    "holder_position": "Менеджер",
    "holder_active": True,
    "kinds": ["letter_out", "contract"],
    "limit_amount": "10000000.00",
    "limit_currency": "UZS",
    "basis": "power_of_attorney",
    "basis_number": "17",
    "basis_date": "2026-03-01",
    "valid_from": "2026-03-01",
    "valid_to": "2027-03-01",
    "vakolat_url": None,
    "note": None,
    "file": {
        "id": "7b8c9d0e-1f2a-4b3c-9d4e-5f6a7b8c9d0e",
        "name": "доверенность.pdf",
        "content_type": "application/pdf",
        "size": 2048,
        "version": 1,
        "sha256": "a" * 64,
        "uploaded_at": "2026-11-05T08:00:00Z",
        "uploaded_by": ADMIN,
    },
    "status": "active",
    "expires_in_days": 116,
    "revoked": None,
    "created_by": ADMIN,
    "created_at": "2026-11-05T08:00:00Z",
    "updated_at": "2026-11-05T08:00:00Z",
}
EDS_DETAIL: dict[str, Any] = {
    **EDS_AUTHORITY,
    "journal": [
        {
            "at": "2026-11-05T08:00:00Z",
            "action": "issued",
            "by": ADMIN,
            "comment": None,
            "details": {},
        },
        {
            "at": "2026-11-05T09:00:00Z",
            "action": "updated",
            "by": ADMIN,
            "comment": None,
            "details": {
                "changed": {
                    "limit_amount": ["5000000.00", "10000000.00"],
                    "kinds": [["a"], ["a", "b"]],
                }
            },
        },
        {
            "at": "2026-11-05T10:00:00Z",
            "action": "file_replaced",
            "by": ADMIN,
            "comment": None,
            "details": {"name": "доверенность.pdf", "version": 1},
        },
        {
            "at": "2026-11-06T04:30:00Z",
            "action": "expiry_reminded",
            "by": None,
            "comment": None,
            "details": {},
        },
    ],
}
FORM: dict[str, Any] = {
    "holder_id": "5",
    "kinds": ["letter_out", "contract"],
    "limit": {"amount": "10000000.00", "currency": "UZS"},
    "basis": "power_of_attorney",
    "basis_number": "17",
    "basis_date": "2026-03-01",
    "valid_from": "2026-03-01",
    "valid_to": "2027-03-01",
}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    fake.answer("GET", "signing/authorities", httpx.Response(200, json={"items": [EDS_AUTHORITY]}))
    fake.answer("POST", "signing/authorities", httpx.Response(201, json=EDS_DETAIL))
    fake.answer("GET", f"signing/authorities/{AUTHORITY_ID}", httpx.Response(200, json=EDS_DETAIL))
    fake.answer(
        "PATCH", f"signing/authorities/{AUTHORITY_ID}", httpx.Response(200, json=EDS_DETAIL)
    )
    fake.answer(
        "POST", f"signing/authorities/{AUTHORITY_ID}/revoke", httpx.Response(200, json=EDS_DETAIL)
    )
    fake.answer(
        "POST",
        f"signing/authorities/{AUTHORITY_ID}/basis-file",
        httpx.Response(200, json=EDS_DETAIL),
    )
    return fake


async def test_only_the_register_keeper_reaches_signing(web: Web, eds: EdsFake) -> None:
    for code in ("DIRECTOR", "MANAGER", "ACCOUNTANT"):
        assert (await web.login([code])).status_code == 200
        assert (await web.client.get(f"{BASE}/authorities")).status_code == 403, code
        assert (await web.send("POST", f"{BASE}/authorities", json=FORM)).status_code == 403
        assert (await web.client.get(f"{BASE}/setup-hint")).status_code == 403
        assert (await web.client.get(f"{BASE}/resolve", params={"kind": "act"})).status_code == 403
    assert eds.calls == []  # отсечено каталогом до EDS


async def test_list_maps_people_money_and_status_filter(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    response = await web.client.get(
        f"{BASE}/authorities", params={"status": "active", "holder_id": "5"}
    )
    assert response.status_code == 200, response.text
    check(response, "/eds/signing/authorities", "get")
    item = response.json()["items"][0]
    assert item["holder"] == {"id": "5", "name": "Алия Каримова", "initials": "АК"}
    assert item["limit"] == {"amount": "10000000.00", "currency": "UZS"}
    assert item["file"] == {
        "name": "доверенность.pdf",
        "content_type": "application/pdf",
        "size": 2048,
        "version": 1,
        "uploaded_at": "2026-11-05T08:00:00Z",
    }
    assert (item["status"], item["expires_in_days"]) == ("active", 116)
    [sent] = eds.made("GET", "signing/authorities")
    assert dict(sent.url.params) == {"status": "active", "crm_user_id": "5"}


async def test_create_sends_numbers_and_money_to_eds_and_maps_the_journal(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    created = await web.send("POST", f"{BASE}/authorities", json=FORM)
    assert created.status_code == 201, created.text
    check(created, "/eds/signing/authorities", "post")
    [sent] = eds.made("POST", "signing/authorities")
    body = json.loads(sent.read())
    assert body["crm_user_id"] == 5
    assert (body["limit_amount"], body["limit_currency"]) == ("10000000.00", "UZS")
    assert body["valid_to"] == "2027-03-01"
    assert body["basis_number"] == "17"
    journal = created.json()["journal"]
    assert [e["action"] for e in journal] == [
        "issued",
        "updated",
        "file_replaced",
        "expiry_reminded",
    ]
    assert journal[1]["changes"] == [
        {"field": "limit_amount", "before": "5000000.00", "after": "10000000.00"},
        {"field": "kinds", "before": "a", "after": "a, b"},
    ]
    assert journal[2]["file_name"] == "доверенность.pdf"
    assert journal[3]["by"] is None


async def test_patch_sends_only_the_fields_that_were_sent_and_null_clears(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    url = f"{BASE}/authorities/{AUTHORITY_ID}"
    response = await web.send("PATCH", url, json={"valid_to": "2027-02-01", "limit": None})
    assert response.status_code == 200, response.text
    check(response, "/eds/signing/authorities/{id}", "patch")
    [sent] = eds.made("PATCH", f"signing/authorities/{AUTHORITY_ID}")
    assert json.loads(sent.read()) == {
        "valid_to": "2027-02-01",
        "limit_amount": None,
        "limit_currency": None,
    }
    assert (await web.send("PATCH", url, json={})).status_code == 200
    assert json.loads(eds.made("PATCH", f"signing/authorities/{AUTHORITY_ID}")[1].read()) == {}


async def test_get_and_revoke(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    got = await web.client.get(f"{BASE}/authorities/{AUTHORITY_ID}")
    check(got, "/eds/signing/authorities/{id}", "get")
    revoked = await web.send(
        "POST", f"{BASE}/authorities/{AUTHORITY_ID}/revoke", json={"reason": "Уволен"}
    )
    assert revoked.status_code == 200
    check(revoked, "/eds/signing/authorities/{id}/revoke", "post")
    [sent] = eds.made("POST", f"signing/authorities/{AUTHORITY_ID}/revoke")
    assert json.loads(sent.read()) == {"reason": "Уволен"}
    short = await web.send(
        "POST", f"{BASE}/authorities/{AUTHORITY_ID}/revoke", json={"reason": " "}
    )
    assert short.status_code == 422


async def test_eds_refusals_keep_reason_and_fields(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "POST",
        f"signing/authorities/{AUTHORITY_ID}/revoke",
        httpx.Response(
            409, json=eds_error_body("CONFLICT", "Полномочие отозвано.", reason="revoked")
        ),
    )
    eds.answer(
        "POST",
        "signing/authorities",
        httpx.Response(
            422,
            json={
                "code": "VALIDATION_FAILED",
                "message": "Проверьте полномочие.",
                "source": "eds",
                "details": {
                    "fields": [
                        {
                            "field": "valid_to",
                            "message": "Доверенность — не более 3 лет.",
                            "type": "value_error",
                        }
                    ]
                },
            },
        ),
    )
    assert (await web.login(["ADMIN"])).status_code == 200
    again = await web.send(
        "POST", f"{BASE}/authorities/{AUTHORITY_ID}/revoke", json={"reason": "Ещё раз"}
    )
    assert (again.status_code, again.json()["details"]["reason"]) == (409, "revoked")
    refused = await web.send("POST", f"{BASE}/authorities", json=FORM)
    assert refused.status_code == 422
    assert "valid_to" in refused.json()["details"]["fields"]


async def test_form_errors_do_not_reach_eds(web: Web, eds: EdsFake) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    bad: list[dict[str, Any]] = [
        {"holder_id": "Иванов"},
        {"kinds": []},
        {"basis": "verbal"},
        {"limit": {"amount": "0.00", "currency": "UZS"}},
        {"valid_from": "01.03.2026"},
    ]
    for patch in bad:
        response = await web.send("POST", f"{BASE}/authorities", json={**FORM, **patch})
        assert response.status_code == 422, patch
    assert eds.made("POST", "signing/authorities") == []


def multipart(content: bytes = b"%PDF-1.7 demo") -> tuple[bytes, str]:
    head = (
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="scan.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    )
    return (
        head.encode() + content + f"\r\n--{BOUNDARY}--\r\n".encode(),
        f"multipart/form-data; boundary={BOUNDARY}",
    )


async def test_basis_file_goes_to_eds_untouched_and_comes_back_as_attachment(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    body, content_type = multipart()
    url = f"{BASE}/authorities/{AUTHORITY_ID}/basis-file"
    uploaded = await web.client.post(
        url, content=body, headers={"content-type": content_type, CSRF_HEADER: web.csrf}
    )
    assert uploaded.status_code == 200, uploaded.text
    check(uploaded, "/eds/signing/authorities/{id}/basis-file", "post")
    [sent] = eds.made("POST", f"signing/authorities/{AUTHORITY_ID}/basis-file")
    assert sent.content == body
    assert sent.headers["content-type"] == content_type

    eds.answer(
        "GET",
        f"signing/authorities/{AUTHORITY_ID}/basis-file",
        httpx.Response(
            200,
            content=b"%PDF-1.7 demo",
            headers={"content-disposition": "attachment; filename*=UTF-8''scan.pdf"},
        ),
    )
    downloaded = await web.client.get(url)
    assert downloaded.status_code == 200
    assert downloaded.content == b"%PDF-1.7 demo"
    assert downloaded.headers["content-disposition"].startswith("attachment")
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-type"].startswith("application/octet-stream")


async def test_basis_file_must_be_multipart_and_not_too_large(web: Web, eds: EdsFake) -> None:
    assert (await web.login(["ADMIN"])).status_code == 200
    url = f"{BASE}/authorities/{AUTHORITY_ID}/basis-file"
    plain = await web.client.post(url, json={}, headers={CSRF_HEADER: web.csrf})
    assert plain.status_code == 422
    assert plain.json()["details"]["reason"] == "multipart_required"
    big, content_type = multipart(b"0" * (26 * 1024 * 1024))
    huge = await web.client.post(
        url, content=big, headers={"content-type": content_type, CSRF_HEADER: web.csrf}
    )
    assert huge.status_code == 413
    assert eds.made("POST", f"signing/authorities/{AUTHORITY_ID}/basis-file") == []


RESOLUTION: dict[str, Any] = {
    "kind": "letter_out",
    "amount": "5000000.00",
    "currency": "UZS",
    "on_date": "2026-11-10",
    "resolved": True,
    "candidates": [
        {
            "signer": HOLDER,
            "position": "Менеджер",
            "acting_for": [{"crm_user_id": 3, "full_name": "Рустам Директоров"}],
            "authority": {
                "id": AUTHORITY_ID,
                "basis": "power_of_attorney",
                "basis_number": "17",
                "basis_date": "2026-03-01",
                "valid_to": "2027-03-01",
                "limit_amount": "10000000.00",
                "limit_currency": "UZS",
            },
            "authorities": [],
            "basis_text": "Действует по доверенности № 17 от 01.03.2026 (до 01.03.2027)",
        }
    ],
    "rejected": [
        {
            "signer": {"crm_user_id": 3, "full_name": "Рустам Директоров"},
            "authority_id": None,
            "reason": "absent",
            "message": "Директор отсутствует по 20.11.2026: задача подписи переходит к Алии.",
        }
    ],
    "explanation": [{"code": "absent", "crm_user_id": 3, "text": "Директор отсутствует."}],
}


async def test_resolve_passes_the_question_and_maps_the_answer(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    RESOLUTION["candidates"][0]["authorities"] = [RESOLUTION["candidates"][0]["authority"]]
    eds.answer("GET", "signing/resolve", httpx.Response(200, json=RESOLUTION))
    assert (await web.login(["ADMIN"])).status_code == 200
    ask = {"kind": "letter_out", "amount": "5000000.00", "currency": "UZS", "on_date": "2026-11-10"}
    response = await web.client.get(f"{BASE}/resolve", params=ask)
    assert response.status_code == 200, response.text
    check(response, "/eds/signing/resolve", "get")
    body = response.json()
    assert body["amount"] == {"amount": "5000000.00", "currency": "UZS"}
    candidate = body["candidates"][0]
    assert candidate["acting_for"] == [{"id": "3", "name": "Рустам Директоров", "initials": "РД"}]
    assert candidate["authority"]["limit"] == {"amount": "10000000.00", "currency": "UZS"}
    assert body["rejected"][0]["reason"] == "absent"
    assert body["explanation"] == [
        {"code": "absent", "person_id": "3", "text": "Директор отсутствует."}
    ]
    [sent] = eds.made("GET", "signing/resolve")
    assert dict(sent.url.params) == ask
    assert (await web.client.get(f"{BASE}/resolve", params={"kind": "Act!"})).status_code == 422
    assert (
        await web.client.get(f"{BASE}/resolve", params={"kind": "act", "amount": "5"})
    ).status_code == 422


async def test_setup_hint_maps_the_director(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    eds.answer(
        "GET",
        "signing/setup-hint",
        httpx.Response(
            200,
            json={
                "has_authorities": False,
                "signatory_name": "Рустам Директоров",
                "signatory_position": "Директор",
                "director": {"crm_user_id": 3, "full_name": "Рустам Директоров"},
            },
        ),
    )
    assert (await web.login(["ADMIN"])).status_code == 200
    response = await web.client.get(f"{BASE}/setup-hint")
    check(response, "/eds/signing/setup-hint", "get")
    assert response.json()["director"]["id"] == "3"
    assert response.json()["has_authorities"] is False


async def test_bad_eds_answer_is_503(web: Web, eds: EdsFake) -> None:
    eds.answer("GET", "signing/authorities", httpx.Response(200, json={"items": [{"id": "x"}]}))
    assert (await web.login(["ADMIN"])).status_code == 200
    assert (await web.client.get(f"{BASE}/authorities")).status_code == 503


async def test_staff_list_is_open_to_the_register_keeper(web: Web, eds: EdsFake) -> None:
    eds.answer("GET", "employees", httpx.Response(200, json={"items": []}))
    assert (await web.login(["ADMIN"])).status_code == 200
    assert (await web.client.get("/api/v1/eds/staff")).status_code == 200
