"""Образец документа настоящим генератором (ДОК-14): `/admin/company/document-samples*`.

Прокси к очереди ERP; ERP — на respx, ответы BFF проверяются по схемам
platform-bff.yaml. Решает ERP (генератор, номер, бланк); здесь — перевод видов
в коды ERP, несохранённые бланк и текст уходят как есть, PDF отдаётся для
просмотра, читатель раздела `company.settings` просит образец, без раздела — отказ.
"""

import json

import httpx
import pytest
import respx

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import EDS_URL, ERP_URL
from tests.roles import custom

API = f"{ERP_URL}/api/v1"


@pytest.fixture
def erp(be: Backends) -> respx.MockRouter:
    """Статус первого запуска ERP: id своей компании — 3."""
    body = {"setup_required": False, "can_setup": False, "own_company_id": 3}
    be.router.get(f"{API}/setup/status/").mock(return_value=httpx.Response(200, json=body))
    return be.router


@pytest.fixture(autouse=True)
def eds(be: Backends) -> None:
    """Вход в EDS — обмен токена (экран «Компания» читает и его)."""
    be.router.post(f"{EDS_URL}/api/v1/auth/sso/exchange").mock(
        return_value=httpx.Response(
            200, json={"access_token": "eds-1", "token_type": "bearer", "expires_in": 900}
        )
    )


SAMPLES = f"{ERP_URL}/api/v1/crm/document-samples"
ID = "a" * 32


async def test_blank_sample_is_queued_with_the_unsaved_draft(
    web: Web,
    erp: respx.MockRouter,
    check: ContractChecker,
) -> None:
    await web.login(["DIRECTOR"])
    route = erp.post(f"{SAMPLES}/").mock(
        return_value=httpx.Response(202, json={"id": ID, "status": "pending"})
    )

    response = await web.send(
        "POST",
        "/api/v1/admin/company/document-samples",
        json={"kind": "invoice", "draft": {"footer_text": "Подвал"}, "language": "en"},
    )

    assert response.status_code == 202
    check(response, "/admin/company/document-samples", "post")
    assert response.json() == {"id": ID, "status": "pending"}
    assert json.loads(route.calls.last.request.content) == {
        "kind": "INV",
        "draft": {"footer_text": "Подвал"},
        "language": "en",
    }


async def test_template_sample_sends_kind_and_unsaved_text(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["DIRECTOR"])
    route = erp.post(f"{SAMPLES}/").mock(
        return_value=httpx.Response(202, json={"id": ID, "status": "pending"})
    )

    await web.send(
        "POST",
        "/api/v1/admin/company/document-samples",
        json={"template_kind": "contract", "body_html": "<p>Текст</p>"},
    )

    assert json.loads(route.calls.last.request.content) == {
        "template_kind": "CONTRACT",
        "body_html": "<p>Текст</p>",
    }


async def test_state_and_pdf(web: Web, erp: respx.MockRouter, check: ContractChecker) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{SAMPLES}/{ID}/").mock(
        return_value=httpx.Response(
            200, json={"id": ID, "status": "ready", "warnings": ["no.such.code"]}
        )
    )
    erp.get(f"{SAMPLES}/{ID}/pdf/").mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.7 test", headers={"content-type": "application/pdf"}
        )
    )

    state = await web.client.get(f"/api/v1/admin/company/document-samples/{ID}")
    pdf = await web.client.get(f"/api/v1/admin/company/document-samples/{ID}/file")

    check(state, "/admin/company/document-samples/{id}", "get")
    assert state.json() == {"id": ID, "status": "ready", "warnings": ["no.such.code"]}
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"] == "inline"
    assert pdf.content == b"%PDF-1.7 test"


async def test_failed_and_expired_samples(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["DIRECTOR"])
    erp.get(f"{SAMPLES}/{ID}/").mock(
        return_value=httpx.Response(
            200, json={"id": ID, "status": "failed", "error": "SAMPLE_RENDER_FAILED"}
        )
    )
    erp.get(f"{SAMPLES}/{'b' * 32}/pdf/").mock(
        return_value=httpx.Response(404, json={"detail": "SAMPLE_NOT_FOUND"})
    )

    failed = await web.client.get(f"/api/v1/admin/company/document-samples/{ID}")
    gone = await web.client.get(f"/api/v1/admin/company/document-samples/{'b' * 32}/file")

    assert failed.json()["error"] == "SAMPLE_RENDER_FAILED"
    assert gone.status_code == 404


async def test_bad_id_is_refused_before_erp(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["DIRECTOR"])
    response = await web.client.get("/api/v1/admin/company/document-samples/..%2F..")
    assert response.status_code in (404, 422)


async def test_reader_asks_for_a_sample_without_the_section_no_one_does(
    web: Web,
    erp: respx.MockRouter,
) -> None:
    reader = custom(50, "Читатель настроек", {"company.settings": "read"})
    await web.login([reader])
    erp.post(f"{SAMPLES}/").mock(
        return_value=httpx.Response(202, json={"id": ID, "status": "pending"})
    )
    ask = await web.send("POST", "/api/v1/admin/company/document-samples", json={"kind": "quote"})
    assert ask.status_code == 202

    nobody = custom(51, "Без настроек", {})
    await web.login([nobody])
    denied = await web.send(
        "POST", "/api/v1/admin/company/document-samples", json={"kind": "quote"}
    )
    assert denied.status_code == 403
