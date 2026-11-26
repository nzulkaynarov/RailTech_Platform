"""ШАБЛ-1: шаблон в Word и обратно — `/document-templates/{id}/word*`.

BFF не разбирает файл: тело `multipart` уходит в ERP как есть (предел 5 МБ), ответ ERP переводится в контракт; тип, архив-бомбу,
закреплённый шаблон и отпечаток текста решает ERP. Здесь проверяется то, что делает BFF: пересылка файла и языка, имя файла
из ERP, предел размера, коды отказов, права (читатель скачивает, загружает только полный доступ).
"""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.roles import custom

ERP = f"{ERP_URL}/api/v1/crm/document-templates"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
BASE = "0123456789abcdef"


def erp_check(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "unchanged": False,
        "formatting_only": False,
        "changes": {
            "items": [
                {
                    "point": "1",
                    "kind": "changed",
                    "ours": "1. Поставка.",
                    "theirs": "1. Продажа.",
                    "segments": [
                        {"op": "equal", "text": "1. "},
                        {"op": "del", "text": "Поставка."},
                        {"op": "ins", "text": "Продажа."},
                    ],
                }
            ],
            "summary": {"changed": ["1"], "added": [], "removed": [], "total": 1, "more": 0},
        },
        "unknown_placeholders": ["warehouse.name"],
        "missing_blocks": [],
        "images_dropped": 2,
        "base": BASE,
        "locked": False,
        "can_apply": True,
        "body_html": "<p>1. Продажа.</p>",
    }
    return {**body, **over}


def erp_template(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": 12,
        "name": "Договор",
        "kind_code": "CONTRACT",
        "kind_name": "Договор",
        "body_html": "<p>1. Продажа.</p>",
        "body_html_uz": "",
        "body_html_en": "",
        "edition": 2,
        "is_locked": False,
        "is_sample": False,
        "is_owned": True,
        "is_active": False,
        "placeholders_used": [],
        "updated_at": "2026-11-26T10:00:00+05:00",
    }
    return {**row, **over}


def upload(web: Web, url: str, data: bytes = b"PK-docx", *, name: str = "t.docx") -> Any:
    return web.client.post(
        url, files={"file": (name, data, DOCX)}, headers={"X-CSRF-Token": web.csrf}
    )


async def test_download_passes_language_and_the_file_name(
    web: Web, be: Backends
) -> None:
    route = be.router.get(f"{ERP}/12/word/").mock(
        return_value=httpx.Response(
            200,
            content=b"PK-docx",
            headers={
                "content-type": DOCX,
                "content-disposition": "attachment; filename=\"template-12.docx\"; filename*=UTF-8''%D0%94",
            },
        )
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.client.get("/api/v1/document-templates/12/word?language=uz")
    assert response.status_code == 200 and response.content == b"PK-docx"
    assert response.headers["content-type"] == DOCX
    assert "filename*=UTF-8''%D0%94" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert route.calls.last.request.url.params["language"] == "uz"


async def test_download_refuses_an_unknown_language(web: Web, be: Backends) -> None:
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.client.get("/api/v1/document-templates/12/word?language=de")
    assert response.status_code == 422


async def test_check_forwards_the_file_untouched_and_translates_the_answer(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    route = be.router.post(f"{ERP}/12/word/").mock(
        return_value=httpx.Response(200, json=erp_check())
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await upload(web, "/api/v1/document-templates/12/word/check?language=ru", b"PK\x03\x04data")
    assert response.status_code == 200, response.text
    check(response, "/document-templates/{id}/word/check", "post")
    body = response.json()
    assert body["unknown_placeholders"] == ["warehouse.name"] and body["can_apply"] is True
    assert body["items"][0]["segments"][1] == {"op": "del", "text": "Поставка."}
    assert body["summary"]["changed"] == ["1"] and body["images_dropped"] == 2
    assert "body_html" not in body  # новый текст наружу не отдаётся: он сохраняется только через «Принять»
    sent = route.calls.last.request
    assert sent.url.params["mode"] == "check" and sent.url.params["language"] == "ru"
    assert b"PK\x03\x04data" in sent.content and sent.headers["content-type"].startswith("multipart/form-data")


async def test_apply_sends_the_base_and_returns_the_template(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    route = be.router.post(f"{ERP}/12/word/").mock(
        return_value=httpx.Response(200, json=erp_template())
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await upload(
        web, f"/api/v1/document-templates/12/word/apply?language=en&base={BASE}"
    )
    assert response.status_code == 200, response.text
    check(response, "/document-templates/{id}/word/apply", "post")
    assert response.json()["edition"] == 2
    params = route.calls.last.request.url.params
    assert (params["mode"], params["language"], params["base"]) == ("apply", "en", BASE)


async def test_apply_needs_a_proper_base(web: Web, be: Backends) -> None:
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await upload(web, "/api/v1/document-templates/12/word/apply?language=ru&base=../x")
    assert response.status_code == 422


async def test_too_large_body_is_cut_before_the_erp(web: Web, be: Backends) -> None:
    route = be.router.post(f"{ERP}/12/word/").mock(return_value=httpx.Response(200, json=erp_check()))
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await upload(
        web, "/api/v1/document-templates/12/word/check?language=ru", b"0" * (6 * 1024 * 1024)
    )
    assert response.status_code == 413
    assert response.json()["details"]["max_bytes"] == 5 * 1024 * 1024
    assert not route.called


async def test_not_multipart_is_refused(web: Web, be: Backends) -> None:
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.send("POST", "/api/v1/document-templates/12/word/check?language=ru", json={})
    assert response.status_code == 422 and response.json()["details"]["reason"] == "multipart_required"


@pytest.mark.parametrize(
    "code", ["WORD_HOSTILE", "WORD_ONLY_DOCX", "WORD_EMPTY", "WORD_UNREADABLE", "WORD_TOO_BIG", "WORD_TOO_COMPLEX"]
)
async def test_erp_refusals_come_as_reasons(web: Web, be: Backends, code: str) -> None:
    be.router.post(f"{ERP}/12/word/").mock(return_value=httpx.Response(400, json={"detail": code}))
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await upload(web, "/api/v1/document-templates/12/word/check?language=ru")
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == code.lower()


async def test_text_changed_and_locked_are_conflicts(web: Web, be: Backends) -> None:
    be.router.post(f"{ERP}/12/word/").mock(
        return_value=httpx.Response(409, json={"detail": "WORD_BASE_CHANGED"})
    )
    be.router.post(f"{ERP}/13/word/").mock(
        return_value=httpx.Response(400, json={"detail": "TEMPLATE_LOCKED"})
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    changed = await upload(web, f"/api/v1/document-templates/12/word/apply?language=ru&base={BASE}")
    locked = await upload(web, f"/api/v1/document-templates/13/word/apply?language=ru&base={BASE}")
    assert changed.status_code == 409 and changed.json()["details"]["reason"] == "word_base_changed"
    assert locked.status_code == 409 and locked.json()["details"]["reason"] == "template_locked"


async def test_reader_downloads_but_does_not_upload(web: Web, be: Backends) -> None:
    be.router.get(f"{ERP}/12/word/").mock(
        return_value=httpx.Response(200, content=b"PK", headers={"content-type": DOCX})
    )
    reader = custom(50, "Читатель настроек", {"company.settings": "read"})
    assert (await web.login([reader])).status_code == 200
    assert (await web.client.get("/api/v1/document-templates/12/word?language=ru")).status_code == 200
    denied = await upload(web, "/api/v1/document-templates/12/word/check?language=ru")
    assert denied.status_code == 403


async def test_submit_names_the_unknown_placeholders(web: Web, be: Backends) -> None:
    be.router.post(f"{ERP}/12/submit/").mock(
        return_value=httpx.Response(
            400,
            json={"detail": "TEMPLATE_UNKNOWN_PLACEHOLDERS", "unknown_placeholders": ["a.b", "c"]},
        )
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.send("POST", "/api/v1/document-templates/contracts/12/submit")
    assert response.status_code == 422
    details = response.json()["details"]
    assert details["reason"] == "template_unknown_placeholders"
    assert details["unknown_placeholders"] == ["a.b", "c"]


async def test_sample_from_a_stored_template_takes_the_text_of_its_language(
    web: Web, be: Backends
) -> None:
    be.router.get(f"{ERP_URL}/api/v1/setup/status/").mock(
        return_value=httpx.Response(
            200, json={"setup_required": False, "can_setup": False, "own_company_id": 3}
        )
    )
    be.router.get(f"{ERP}/12/").mock(
        return_value=httpx.Response(200, json=erp_template(body_html_uz="<p>Shartnoma</p>"))
    )
    route = be.router.post(f"{ERP_URL}/api/v1/crm/document-samples/").mock(
        return_value=httpx.Response(202, json={"id": "a" * 32, "status": "pending"})
    )
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    for language, text in (("uz", "<p>Shartnoma</p>"), ("en", "<p>1. Продажа.</p>")):
        response = await web.send(
            "POST",
            "/api/v1/admin/company/document-samples",
            json={"template_id": "12", "language": language},
        )
        assert response.status_code == 202, response.text
        assert json.loads(route.calls.last.request.content) == {
            "template_kind": "CONTRACT",
            "body_html": text,
            "language": language,
        }
