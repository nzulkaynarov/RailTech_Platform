"""CRM · База знаний (W13-A5, контракт BFF 0.11.0): прокси к CRM, `/crm/kb/*` и `/crm/sandbox/*`.

CRM — на respx (`kb_support`), ответы BFF проверяются по схемам platform-bff.yaml. Проверяется то,
что делает BFF: раздел каталога (чтение — `crm.leads` или `admin`, правка и песочница —
`admin: full`, 403 до CRM), токен сотрудника в CRM, загрузка файла без разбора multipart и с
пределом размера, перевод ошибок CRM (формат документа, размер, 409 индексации) в единый
формат `Error`.
Решения (формат, порог поиска, ответ бота) — за CRM.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.api.crm_kb import MAX_BODY_BYTES, MAX_UPLOAD_BYTES
from app.clients.base import PROBE_TIMEOUT_SECONDS
from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.kb_support import CrmBotFake

BASE = "/api/v1/crm/kb"
SANDBOX = "/api/v1/crm/sandbox"


@pytest.fixture
def crm(be: Backends) -> CrmBotFake:
    return CrmBotFake(be)


# (адрес BFF, шаблон пути контракта)
READS: tuple[tuple[str, str], ...] = (
    (f"{BASE}/documents", "/crm/kb/documents"),
    (f"{BASE}/documents/1", "/crm/kb/documents/{id}"),
    (f"{BASE}/documents/1/chunks", "/crm/kb/documents/{id}/chunks"),
    (f"{BASE}/gaps", "/crm/kb/gaps"),
    (f"{BASE}/products", "/crm/kb/products"),
)
SEARCH = ("POST", f"{BASE}/search", "/crm/kb/search", {"query": "срок поставки"})
MANUAL = {"title": "Гарантия", "markdown": "## Гарантия\n\n12 месяцев.", "language": "ru"}
# (метод, адрес BFF, шаблон пути контракта, тело) — все, что требует `admin: full`
WRITES: tuple[tuple[str, str, str, dict[str, Any] | None], ...] = (
    ("POST", f"{BASE}/documents/manual", "/crm/kb/documents/manual", MANUAL),
    ("PATCH", f"{BASE}/documents/1", "/crm/kb/documents/{id}", {"is_active": False}),
    ("POST", f"{BASE}/documents/1/reingest", "/crm/kb/documents/{id}/reingest", None),
    ("POST", f"{BASE}/gaps/1/resolve", "/crm/kb/gaps/{id}/resolve", {"document_id": 1}),
    ("POST", f"{BASE}/gaps/1/ignore", "/crm/kb/gaps/{id}/ignore", None),
    ("POST", f"{BASE}/gaps/1/reopen", "/crm/kb/gaps/{id}/reopen", None),
    (
        "POST",
        f"{SANDBOX}/messages",
        "/crm/sandbox/messages",
        {"text": "Сколько стоит доставка?", "language": "ru"},
    ),
    ("POST", f"{SANDBOX}/reset", "/crm/sandbox/reset", None),
)
BOUNDARY = "demo-boundary-7f3a"


def multipart(
    content: bytes = b"---\ntitle: FAQ\n---\n# FAQ\n", *, filename: str = "faq.md"
) -> tuple[bytes, str]:
    """Тело multipart загрузки так, как его шлёт браузер: файл и поля формы."""
    parts = [
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/markdown\r\n\r\n",
    ]
    tail = "".join(
        f'\r\n--{BOUNDARY}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}'
        for name, value in (("title", "Вопросы и ответы"), ("language", "ru"))
    )
    body = parts[0].encode() + content + tail.encode() + f"\r\n--{BOUNDARY}--\r\n".encode()
    return body, f"multipart/form-data; boundary={BOUNDARY}"


async def upload(web: Web, body: bytes | AsyncIterator[bytes], content_type: str) -> Any:
    return await web.client.post(
        f"{BASE}/documents",
        content=body,
        headers={"content-type": content_type, CSRF_HEADER: web.csrf},
    )


# --- права: раздел каталога, до CRM -------------------------------------------------------------


@pytest.mark.parametrize("role", ["SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_role_without_leads_or_admin_gets_403_on_every_endpoint(
    web: Web, crm: CrmBotFake, role: str
) -> None:
    """Ни `crm.leads`, ни `admin` — 403 в BFF на каждом эндпоинте, CRM не вызывается."""
    await web.login([role])

    for url, _ in READS:
        response = await web.client.get(url)
        assert response.status_code == 403, url
        assert response.json()["details"] == {"resource": "crm.leads", "need": "read"}
    gaps = await web.client.get(f"{BASE}/gaps?status=open")
    assert gaps.status_code == 403
    s_method, s_url, _, s_body = SEARCH
    assert (await web.send(s_method, s_url, json=s_body)).status_code == 403  # type: ignore[arg-type]
    for method, url, _, body in WRITES:
        response = await web.send(method, url, json=body)  # type: ignore[arg-type]
        assert response.status_code == 403, (method, url)
        assert response.json()["details"] == {"resource": "admin", "need": "full"}
    sent, content_type = multipart()
    assert (await upload(web, sent, content_type)).status_code == 403
    assert crm.count == 0


async def test_manager_reads_but_cannot_change_anything(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    """Менеджер (`crm.leads`) читает базу знаний и ищет; правка, песочница, загрузка — 403."""
    await web.login(["MANAGER"])

    for url, template in READS:
        response = await web.client.get(url)
        assert response.status_code == 200, url
        check(response, template, "get")
    s_method, s_url, s_template, s_body = SEARCH
    found = await web.send(s_method, s_url, json=s_body)  # type: ignore[arg-type]
    assert found.status_code == 200
    check(found, s_template, "post")
    reads = crm.count
    for method, url, _, body in WRITES:
        response = await web.send(method, url, json=body)  # type: ignore[arg-type]
        assert response.status_code == 403, (method, url)
    sent, content_type = multipart()
    assert (await upload(web, sent, content_type)).status_code == 403
    assert crm.count == reads


async def test_director_reads_but_every_change_is_403(web: Web, crm: CrmBotFake) -> None:
    """Директор (`crm.leads` и `admin` — чтение) читает; изменения — 403 до CRM."""
    await web.login(["DIRECTOR"])

    for url, _ in READS:
        assert (await web.client.get(url)).status_code == 200, url
    reads = crm.count
    for method, url, _, body in WRITES:
        assert (await web.send(method, url, json=body)).status_code == 403  # type: ignore[arg-type]
    assert crm.count == reads


async def test_admin_without_leads_reads_kb_through_admin_section(
    web: Web, crm: CrmBotFake
) -> None:
    """Администратор без `crm.leads` читает базу знаний (раздел `admin`), продукты — решает CRM."""
    await web.login(["ADMIN"])
    crm.error("GET", "kb/products", 403, "forbidden")

    docs = await web.client.get(f"{BASE}/documents")
    products = await web.client.get(f"{BASE}/products")

    assert docs.status_code == 200
    assert products.status_code == 403
    assert products.json()["code"] == "FORBIDDEN"
    assert products.json()["source"] == "crm"


async def test_session_and_csrf_are_required(web: Web, crm: CrmBotFake) -> None:
    anonymous = await web.client.get(f"{BASE}/documents")
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "SESSION_EXPIRED"

    await web.login(["ADMIN"])
    no_csrf = await web.send("POST", f"{BASE}/documents/1/reingest", csrf="x")
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"
    assert crm.requests("POST", "kb/documents/1/reingest") == []
    sent, content_type = multipart()
    forged = await web.client.post(
        f"{BASE}/documents",
        content=sent,
        headers={"content-type": content_type, CSRF_HEADER: "x"},
    )
    assert forged.status_code == 403
    assert crm.requests("POST", "kb/documents") == []


# --- каждый эндпоинт: админ, токен сотрудника, ответ по контракту --------------------------------


@pytest.mark.parametrize(("url", "template"), READS)
async def test_admin_reads_every_endpoint_with_staff_token(
    web: Web, crm: CrmBotFake, check: ContractChecker, url: str, template: str
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get(url)

    assert response.status_code == 200
    check(response, template, "get")
    assert crm.calls, "CRM не вызывали"
    for call in crm.calls:
        assert call.headers["authorization"].startswith("Bearer crm-access-")


@pytest.mark.parametrize(("method", "url", "template", "body"), WRITES)
async def test_admin_runs_every_action(
    web: Web,
    crm: CrmBotFake,
    check: ContractChecker,
    method: str,
    url: str,
    template: str,
    body: dict[str, Any] | None,
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(method, url, json=body)  # type: ignore[arg-type]

    expected = {
        "/crm/kb/documents/manual": 201,
        "/crm/sandbox/reset": 204,
    }.get(template, 200)
    assert response.status_code == expected, response.text
    check(response, template, method.lower())
    sent = crm.calls[-1]
    assert sent.method == method
    assert sent.headers["authorization"].startswith("Bearer crm-access-")


async def test_search_for_admin_matches_contract(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(
        "POST",
        f"{BASE}/search",
        json={"query": "срок поставки", "language": "ru", "top_k": 3},
    )

    assert response.status_code == 200
    check(response, "/crm/kb/search", "post")
    assert crm.body("POST", "kb/search") == {
        "query": "срок поставки",
        "language": "ru",
        "product_key": None,
        "top_k": 3,
    }
    assert response.json()["confident"] is True
    assert response.json()["hits"][0]["document_title"] == "Доставка и сроки 1"


async def test_calls_that_take_longer_wait_for_crm_up_to_30_seconds(
    web: Web, crm: CrmBotFake
) -> None:
    """Поиск, песочница и загрузка идут через модель и S3: ждут CRM как проба; чтение — обычно."""
    await web.login(["ADMIN"])

    await web.client.get(f"{BASE}/documents")
    await web.send("POST", f"{SANDBOX}/messages", json={"text": "Привет"})
    await web.send("POST", f"{BASE}/search", json={"query": "срок"})

    assert crm.last("GET", "kb/documents").extensions["timeout"]["read"] == 5.0
    for path in ("sandbox/messages", "kb/search"):
        timeout = crm.last("POST", path).extensions["timeout"]["read"]
        assert timeout == PROBE_TIMEOUT_SECONDS, path


# --- документы ----------------------------------------------------------------------------------


async def test_document_list_forwards_active_filter(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN"])

    await web.client.get(f"{BASE}/documents?active=false")

    assert crm.last("GET", "kb/documents").url.params["active"] == "false"
    first = await web.client.get(f"{BASE}/documents")
    assert "active" not in crm.last("GET", "kb/documents").url.params
    assert first.json()["items"][0]["ingest_status"] == "done"


async def test_patch_sends_only_the_fields_that_changed(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN"])

    response = await web.send("PATCH", f"{BASE}/documents/5", json={"is_active": False})

    assert response.status_code == 200
    assert crm.body("PATCH", "kb/documents/5") == {"is_active": False}


async def test_manual_document_goes_to_crm_as_is(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(
        "POST", f"{BASE}/documents/manual", json={**MANUAL, "product_key": "rails", "gap_id": 3}
    )

    assert response.status_code == 201
    assert response.json() == {"id": 77}
    assert crm.body("POST", "kb/documents/manual") == {
        **MANUAL,
        "product_key": "rails",
        "gap_id": 3,
    }


async def test_reingest_of_a_document_being_indexed_is_409(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    crm.error("POST", "kb/documents/3/reingest", 409, "conflict", "document_indexing")
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/documents/3/reingest")

    assert response.status_code == 409
    check(response, "/crm/kb/documents/{id}/reingest", "post")
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "document_indexing"


async def test_search_without_embedding_key_is_422_not_crm_down(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    """C2A-G-6: CRM отвечает 422 `model_key_required` — BFF отдаёт его, не 503 «CRM не отвечает»."""
    crm.error("POST", "kb/search", 422, "validation_failed", "model_key_required")
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/search", json={"query": "срок поставки"})

    assert response.status_code == 422
    check(response, "/crm/kb/search", "post")
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"]["reason"] == "model_key_required"


async def test_search_with_unreachable_model_gateway_is_502_integration_failed(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    crm.error("POST", "kb/search", 502, "upstream_unavailable", "litellm_unavailable")
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/search", json={"query": "срок поставки"})

    assert response.status_code == 502
    check(response, "/crm/kb/search", "post")
    assert response.json()["code"] == "INTEGRATION_FAILED"
    assert response.json()["details"]["reason"] == "litellm_unavailable"


async def test_unknown_document_is_404(web: Web, crm: CrmBotFake, check: ContractChecker) -> None:
    crm.error("GET", "kb/documents/9", 404, "not_found")
    await web.login(["ADMIN"])

    response = await web.client.get(f"{BASE}/documents/9")

    assert response.status_code == 404
    check(response, "/crm/kb/documents/{id}", "get")
    assert response.json()["code"] == "NOT_FOUND"


async def test_bad_ids_are_rejected_before_crm(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN"])

    assert (await web.client.get(f"{BASE}/documents/0")).status_code == 422
    assert (await web.client.get(f"{BASE}/documents/abc")).status_code == 422
    assert (await web.send("POST", f"{BASE}/gaps/0/ignore")).status_code == 422
    assert crm.count == 0


async def test_chunks_and_gap_page_match_contract(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    chunks = await web.client.get(f"{BASE}/documents/1/chunks")
    gaps = await web.client.get(f"{BASE}/gaps?status=resolved&language=uz&limit=10&offset=20")

    assert [c["position"] for c in chunks.json()["items"]] == [0, 1]
    check(gaps, "/crm/kb/gaps", "get")
    params = crm.last("GET", "kb/gaps").url.params
    assert dict(params) == {"status": "resolved", "language": "uz", "limit": "10", "offset": "20"}
    assert gaps.json()["total"] == 2


async def test_gap_query_is_validated_in_bff(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN"])

    for query in ("status=deleted", "limit=0", "limit=201", "offset=-1", "language=de"):
        response = await web.client.get(f"{BASE}/gaps?{query}")
        assert response.status_code == 422, query
        assert response.json()["code"] == "VALIDATION_FAILED"
    assert crm.count == 0


# --- загрузка файла -----------------------------------------------------------------------------


async def test_upload_forwards_the_multipart_body_untouched(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    body, content_type = multipart()

    response = await upload(web, body, content_type)

    assert response.status_code == 201, response.text
    check(response, "/crm/kb/documents", "post")
    assert response.json() == {"id": 77}
    sent = crm.last("POST", "kb/documents")
    assert sent.content == body
    assert sent.headers["content-type"] == content_type
    assert sent.headers["authorization"].startswith("Bearer crm-access-")
    assert sent.extensions["timeout"]["read"] == PROBE_TIMEOUT_SECONDS


async def test_upload_must_be_multipart(web: Web, crm: CrmBotFake, check: ContractChecker) -> None:
    await web.login(["ADMIN"])

    response = await upload(web, b'{"file": "x"}', "application/json")

    assert response.status_code == 422
    check(response, "/crm/kb/documents", "post")
    assert response.json()["details"] == {"fields": ["file"], "reason": "multipart_required"}
    assert crm.count == 0


async def test_upload_larger_than_the_limit_is_refused_without_calling_crm(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    """Файл больше 25 МБ: отказ по `Content-Length`, не читая тело и не дойдя до CRM."""
    await web.login(["ADMIN"])
    body, content_type = multipart(b"x" * (MAX_UPLOAD_BYTES + 100_000))

    response = await upload(web, body, content_type)

    assert response.status_code == 422
    check(response, "/crm/kb/documents", "post")
    assert response.json()["details"] == {
        "fields": ["file"],
        "reason": "file_too_large",
        "max_bytes": MAX_UPLOAD_BYTES,
    }
    assert crm.count == 0


async def test_upload_without_declared_length_is_cut_at_the_limit(
    web: Web, crm: CrmBotFake
) -> None:
    """Тело без `Content-Length` (chunked) читается кусками и обрывается на пределе."""
    await web.login(["ADMIN"])
    body, content_type = multipart(b"y" * (MAX_BODY_BYTES + 1))

    async def pieces() -> AsyncIterator[bytes]:
        for start in range(0, len(body), 1_000_000):
            yield body[start : start + 1_000_000]

    response = await upload(web, pieces(), content_type)

    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "file_too_large"
    assert crm.count == 0


async def test_upload_of_a_file_at_the_limit_goes_through(web: Web, crm: CrmBotFake) -> None:
    await web.login(["ADMIN"])
    body, content_type = multipart(b"z" * MAX_UPLOAD_BYTES)

    response = await upload(web, body, content_type)

    assert response.status_code == 201
    assert len(crm.last("POST", "kb/documents").content) == len(body)


@pytest.mark.parametrize(
    ("reason", "extra"),
    [
        ("kb_markdown_only", {}),
        ("file_empty", {}),
        (
            "kb_format",
            {
                "rule": "front_matter_missing",
                "detail": "В начале файла нет front matter",
                "messages": {"ru": "Добавьте front matter", "uz": "Qo‘shing", "en": "Add it"},
                "format_doc": "docs/kb/FORMAT.md",
            },
        ),
    ],
)
async def test_crm_refusal_of_the_file_reaches_the_screen_with_its_reason(
    web: Web, crm: CrmBotFake, check: ContractChecker, reason: str, extra: dict[str, Any]
) -> None:
    crm.error("POST", "kb/documents", 422, "validation_failed", reason, field="file", **extra)
    await web.login(["ADMIN"])
    body, content_type = multipart(b"not markdown", filename="faq.txt")

    response = await upload(web, body, content_type)

    assert response.status_code == 422
    check(response, "/crm/kb/documents", "post")
    error = response.json()
    assert error["code"] == "VALIDATION_FAILED"
    assert error["details"]["reason"] == reason
    assert error["details"]["fields"] == ["file"]
    if extra:
        assert error["details"]["rule"] == "front_matter_missing"
        assert error["details"]["messages"] == extra["messages"]
        assert "format_doc" not in error["details"]


async def test_upload_when_crm_answers_502_is_an_integration_failure(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    crm.error("POST", "kb/documents", 502, "upstream_unavailable", "storage_unavailable")
    await web.login(["ADMIN"])
    body, content_type = multipart()

    response = await upload(web, body, content_type)

    assert response.status_code == 502
    check(response, "/crm/kb/documents", "post")
    assert response.json()["code"] == "INTEGRATION_FAILED"


# --- песочница ----------------------------------------------------------------------------------


async def test_sandbox_message_shows_reply_and_why(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(
        "POST", f"{SANDBOX}/messages", json={"text": "Сколько стоит?", "language": "uz"}
    )

    assert response.status_code == 200
    check(response, "/crm/sandbox/messages", "post")
    assert crm.body("POST", "sandbox/messages") == {"text": "Сколько стоит?", "language": "uz"}
    assert response.json()["why"]["decision"] == "answer"
    assert response.json()["replies"][0]["buttons"] == ["Передать менеджеру"]


async def test_sandbox_message_defaults_to_russian_and_validates_length(
    web: Web, crm: CrmBotFake
) -> None:
    await web.login(["ADMIN"])

    await web.send("POST", f"{SANDBOX}/messages", json={"text": "Привет"})
    empty = await web.send("POST", f"{SANDBOX}/messages", json={"text": ""})
    long = await web.send("POST", f"{SANDBOX}/messages", json={"text": "я" * 4001})

    assert crm.body("POST", "sandbox/messages")["language"] == "ru"
    assert empty.status_code == 422
    assert long.status_code == 422
    assert len(crm.requests("POST", "sandbox/messages")) == 1


async def test_sandbox_model_failure_is_an_integration_failure(
    web: Web, crm: CrmBotFake, check: ContractChecker
) -> None:
    crm.error("POST", "sandbox/messages", 502, "upstream_unavailable", "litellm_unavailable")
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{SANDBOX}/messages", json={"text": "Привет"})

    assert response.status_code == 502
    check(response, "/crm/sandbox/messages", "post")
    assert response.json()["code"] == "INTEGRATION_FAILED"
    assert response.json()["details"]["reason"] == "litellm_unavailable"


async def test_crm_down_is_503_with_source(web: Web, crm: CrmBotFake) -> None:
    crm.error("GET", "kb/documents", 500, "internal")
    await web.login(["ADMIN"])

    response = await web.client.get(f"{BASE}/documents")

    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
    assert response.json()["source"] == "crm"


async def test_crm_answer_of_another_shape_is_503_not_a_crash(web: Web, crm: CrmBotFake) -> None:
    crm.answer("GET", "kb/documents/1", 200, {"id": "не число"})
    await web.login(["ADMIN"])

    response = await web.client.get(f"{BASE}/documents/1")

    assert response.status_code == 503
    assert response.json()["details"]["reason"] == "bad_response"
