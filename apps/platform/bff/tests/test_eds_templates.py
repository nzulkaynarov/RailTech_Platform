"""Шаблоны писем и служебок EDS (TPL-4, план 3.6): прокси BFF и права."""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import EdsFake

TEMPLATE_ID = "0b0e3c8a-6f1d-4c2e-9a7b-3d2f1e0c9b8a"
HASH = "a" * 64


def body(lang: str, text: str) -> dict[str, Any]:
    return {
        "version": 1,
        "lang": lang,
        "doc": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        },
    }


TEMPLATE: dict[str, Any] = {
    "id": TEMPLATE_ID,
    "kind": "letter",
    "name": "Деловое письмо",
    "variants": {"ru": body("ru", "Уважаемые коллеги!"), "uz": body("uz", "Hurmatli hamkasblar!")},
    "languages": ["ru", "uz"],
    "is_default": True,
    "active": True,
    "origin": "builtin",
    "changed": False,
    "updated_at": "2026-11-15T09:00:00Z",
}
PREVIEW = {"hash": HASH, "status": "pending", "error": None, "pages": None}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    fake.answer("GET", "templates", httpx.Response(200, json={"items": [TEMPLATE]}))
    fake.answer("POST", "templates", httpx.Response(201, json=TEMPLATE))
    fake.answer("POST", f"templates/{TEMPLATE_ID}/reset", httpx.Response(200, json=TEMPLATE))
    fake.answer("POST", "template-previews", httpx.Response(202, json=PREVIEW))
    fake.answer(
        "GET",
        f"template-previews/{HASH}/file",
        httpx.Response(
            200, content=b"%PDF-1.7 preview", headers={"content-type": "application/pdf"}
        ),
    )
    return fake


async def test_reader_lists_and_previews_editor_saves_and_resets(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["MANAGER"])).status_code == 200
    listed = await web.client.get("/api/v1/eds/templates", params={"kind": "letter"})
    check(listed, "/eds/templates", "get")
    assert listed.json()["items"][0]["languages"] == ["ru", "uz"]
    preview = await web.send(
        "POST", "/api/v1/eds/template-previews", json={"body": body("uz", "Salom")}
    )
    assert preview.status_code == 202
    check(preview, "/eds/template-previews", "post")
    pdf = await web.client.get(f"/api/v1/eds/template-previews/{HASH}/file")
    assert (pdf.status_code, pdf.content) == (200, b"%PDF-1.7 preview")
    form = {
        "kind": "letter",
        "name": "Ответ налоговой",
        "variants": {"ru": body("ru", "Направляем.")},
    }
    assert (await web.send("POST", "/api/v1/eds/templates", json=form)).status_code == 403

    assert (await web.login(["REGISTRAR"])).status_code == 200
    created = await web.send("POST", "/api/v1/eds/templates", json=form)
    assert created.status_code == 201
    check(created, "/eds/templates", "post")
    sent = json.loads(eds.made("POST", "templates")[-1].content)
    assert sent["variants"] == {"ru": body("ru", "Направляем.")}
    reset = await web.send("POST", f"/api/v1/eds/templates/{TEMPLATE_ID}/reset")
    check(reset, "/eds/templates/{id}/reset", "post")
    assert (await web.client.get("/api/v1/eds/template-previews/not-a-hash")).status_code == 422
