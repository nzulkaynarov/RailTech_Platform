"""EDS · Создать документ и «Мои документы» (D1-5, контракт BFF 0.17.0): прокси к EDS,
`/eds/documents*`.

EDS — на respx (`eds_documents_support`), ответы BFF проверяются по схемам platform-bff.yaml.
Проверяется то, что
делает BFF: раздел каталога (403 до EDS), вход в EDS по SSO-токену CRM `aud=eds` и отказ
`eds_not_granted`, токен
сотрудника в EDS, «Мои» и «Все» (реестр), карточка с шагами маршрута, создание и сохранение с
отправкой, ошибки
EDS в едином формате, загрузка файла без разбора multipart и с пределом размера, скачивание потоком,
поиск заявки.
Решения (право на тип, номера, маршрут, статусы) — за EDS.
"""

from typing import Any

import httpx
import pytest

from app.api.eds_documents import MAX_BODY_BYTES, MAX_UPLOAD_BYTES
from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.eds_documents_support import (
    DOC_ID,
    FILE_ID,
    ROUTE_ID,
    TOKEN,
    EdsFake,
    document,
    file_ref,
    registry_item,
)
from tests.feeds_support import deal_matches
from tests.roles import custom

BASE = "/api/v1/eds"
NO_EDS = custom(50, "Без EDS", {"dashboard.queue": "full"})
FORM: dict[str, Any] = {
    "kind": "memo",
    "subject": "Закупка канцтоваров",
    "text": "Прошу согласовать закупку канцтоваров на квартал.",
    "amount": {"amount": "1500000.00", "currency": "UZS"},
    "due_date": "2999-11-05",
    "file_ids": [FILE_ID],
    "erp_deal_id": 905,
}
BOUNDARY = "demo-boundary-5d1e"


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    return EdsFake(be)


def multipart(content: bytes = b"%PDF-1.4 demo", filename: str = "schet.pdf") -> tuple[bytes, str]:
    head = (
        f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    )
    body = head.encode() + content + f"\r\n--{BOUNDARY}--\r\n".encode()
    return body, f"multipart/form-data; boundary={BOUNDARY}"


async def upload(web: Web, body: bytes, content_type: str) -> httpx.Response:
    return await web.client.post(
        f"{BASE}/document-files",
        content=body,
        headers={"content-type": content_type, CSRF_HEADER: web.csrf},
    )


# --- права: раздел каталога, до EDS ---------------------------------------------------------------


async def test_role_without_eds_sections_gets_403_everywhere_and_eds_is_not_called(
    web: Web, eds: EdsFake
) -> None:
    await web.login([NO_EDS])

    for url in (
        f"{BASE}/documents",
        f"{BASE}/documents/{DOC_ID}",
        f"{BASE}/document-files/{FILE_ID}",
        f"{BASE}/deal-options",
    ):
        assert (await web.client.get(url)).status_code == 403, url
    assert (await web.send("POST", f"{BASE}/documents", json=FORM)).status_code == 403
    assert (await web.send("PUT", f"{BASE}/documents/{DOC_ID}", json=FORM)).status_code == 403
    sent, content_type = multipart()
    assert (await upload(web, sent, content_type)).status_code == 403
    assert eds.count == 0
    assert eds.issued == []


async def test_registry_scope_needs_a_registry_section(web: Web, eds: EdsFake) -> None:
    """Администратор (только `eds.memo.create`) видит «Мои», но не реестр компании: 403 до EDS."""
    await web.login(["ADMIN"])

    mine = await web.client.get(f"{BASE}/documents")
    registry = await web.client.get(f"{BASE}/documents?scope=all")

    assert mine.status_code == 200
    assert registry.status_code == 403
    assert registry.json()["details"] == {"resource": "eds.inbox", "need": "read"}
    assert eds.requests("GET", "registry") == []


async def test_session_and_csrf_are_required(web: Web, eds: EdsFake) -> None:
    anonymous = await web.client.get(f"{BASE}/documents")
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "SESSION_EXPIRED"

    await web.login(["MANAGER"])
    forged = await web.send("POST", f"{BASE}/documents", json=FORM, csrf="x")
    assert forged.status_code == 403
    assert forged.json()["code"] == "CSRF_FAILED"
    assert eds.requests("POST", "documents") == []
    sent, content_type = multipart()
    stolen = await web.client.post(
        f"{BASE}/document-files",
        content=sent,
        headers={"content-type": content_type, CSRF_HEADER: "x"},
    )
    assert stolen.status_code == 403
    assert eds.requests("POST", "files") == []


async def test_eds_not_granted_is_403_with_reason(web: Web, eds: EdsFake) -> None:
    """
    CRM не выдаёт токен для EDS (нет `permissions.eds`): 403 `eds_not_granted`, сессия Платформы
    жива.
    """
    await web.login(["MANAGER"])
    eds.sso_status = 403

    response = await web.client.get(f"{BASE}/documents")

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["details"]["reason"] == "eds_not_granted"
    assert (await web.client.get("/api/v1/me")).status_code == 200


# --- список ---------------------------------------------------------------------------------------


async def test_mine_lists_own_documents_with_staff_token(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])

    response = await web.client.get(
        f"{BASE}/documents?kind=memo&kind=report&status=on_approval&status=draft&limit=20&cursor=c1"
    )

    assert response.status_code == 200, response.text
    check(response, "/eds/documents", "get")
    row = response.json()["items"][0]
    assert (row["kind"], row["number"], row["status"], row["openable"]) == (
        "memo",
        "СЗ-2026/031",
        "on_approval",
        True,
    )
    assert row["amount"] == {"amount": "1500000.00", "currency": "UZS"}
    sent = eds.last("GET", "documents")
    assert sent.headers["authorization"] == f"Bearer {TOKEN}1"
    query = sent.url.params
    assert query["mine"] == "true"
    assert query.get_list("kind") == ["memo", "report"]
    assert query.get_list("status") == ["on_approval", "draft"]
    assert (query["limit"], query["cursor"]) == ("20", "c1")


async def test_mine_ignores_kinds_that_are_not_documents(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])

    response = await web.client.get(f"{BASE}/documents?kind=letter_in&kind=quote")

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}
    assert eds.requests("GET", "documents") == []


async def test_all_reads_the_registry(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    eds.answer(
        "GET",
        "registry",
        200,
        {
            "items": [
                registry_item(),
                registry_item(
                    "40000000-0000-4000-8000-000000000001",
                    kind="letter_in",
                    number="ВХ-104/26",
                    title="Запрос цен на рельсы",
                    status="awaiting_resolution",
                    responsible=None,
                ),
            ],
            "next_cursor": "cur-2",
        },
    )

    response = await web.client.get(f"{BASE}/documents?scope=all&kind=memo&kind=letter_in&q=рельсы")

    assert response.status_code == 200, response.text
    check(response, "/eds/documents", "get")
    body = response.json()
    assert body["next_cursor"] == "cur-2"
    memo, letter = body["items"]
    assert (memo["subject"], memo["author"]["full_name"], memo["amount"], memo["openable"]) == (
        "Закупка канцтоваров",
        "Рустам Директоров",
        None,
        True,
    )
    assert (letter["kind"], letter["author"], letter["openable"]) == ("letter_in", None, False)
    query = eds.last("GET", "registry").url.params
    assert query.get_list("kind") == ["memo", "letter_in"]
    assert query["q"] == "рельсы"
    assert "mine" not in query


async def test_list_validates_filters_before_eds(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])

    for url in (
        f"{BASE}/documents?scope=everything",
        f"{BASE}/documents?kind=contract",
        f"{BASE}/documents?status=DROP TABLE",
        f"{BASE}/documents?limit=0",
    ):
        response = await web.client.get(url)
        assert response.status_code == 422, url
        assert response.json()["code"] == "VALIDATION_FAILED"
    assert eds.count == 0


async def test_eds_down_is_503_with_source(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    eds.answer("GET", "documents", 503, {"code": "INTERNAL_ERROR", "message": "x", "source": "eds"})

    response = await web.client.get(f"{BASE}/documents")

    assert response.status_code == 503
    assert (response.json()["code"], response.json()["source"]) == ("BACKEND_UNAVAILABLE", "eds")


# --- карточка -------------------------------------------------------------------------------------


async def test_card_assembles_route_decisions_and_edit_flag(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    eds.answer(
        "GET",
        f"documents/{DOC_ID}",
        200,
        document(
            status="returned",
            amount={"amount": "250000.00", "currency": "UZS"},
            files=[file_ref()],
            erp_deal_id=905,
            deal_number="ЗВ-2026-104",
            approval_id=ROUTE_ID,
            decisions=[
                {
                    "round": 1,
                    "step": 1,
                    "decision": "return",
                    "comment": "Добавьте смету",
                    "by": {"crm_user_id": 3, "full_name": "Рустам Директоров"},
                    "at": "2026-10-26T10:00:00Z",
                }
            ],
        ),
    )

    response = await web.client.get(f"{BASE}/documents/{DOC_ID}")

    assert response.status_code == 200, response.text
    check(response, "/eds/documents/{id}", "get")
    body = response.json()
    assert [(s["label"], s["status"]) for s in body["route"]] == [
        ("Директор", "current"),
        ("Бухгалтер", "pending"),
    ]
    assert body["decisions"][0]["comment"] == "Добавьте смету"
    assert body["decisions"][0]["by"]["full_name"] == "Рустам Директоров"
    assert body["deal"] == {"erp_deal_id": 905, "number": "ЗВ-2026-104"}
    assert body["files"] == [
        {"id": FILE_ID, "name": "schet.pdf", "content_type": "application/pdf", "size": 2048}
    ]
    assert body["can_edit"] is True  # автор (id 7) и статус «возвращён»
    assert (
        eds.last("GET", f"approvals/{ROUTE_ID}").headers["authorization"].startswith("Bearer eds-")
    )


async def test_card_of_someone_elses_or_sent_document_cannot_be_edited(
    web: Web, eds: EdsFake
) -> None:
    await web.login(["MANAGER"])
    other = {"crm_user_id": 99, "full_name": "Другой Автор"}
    eds.answer("GET", f"documents/{DOC_ID}", 200, document(author=other))
    assert (await web.client.get(f"{BASE}/documents/{DOC_ID}")).json()["can_edit"] is False

    eds.answer("GET", f"documents/{DOC_ID}", 200, document(status="on_approval"))
    assert (await web.client.get(f"{BASE}/documents/{DOC_ID}")).json()["can_edit"] is False


async def test_card_without_route_access_still_opens(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    eds.answer(
        "GET", f"documents/{DOC_ID}", 200, document(status="on_approval", approval_id=ROUTE_ID)
    )
    eds.error("GET", f"approvals/{ROUTE_ID}", 404, "NOT_FOUND")

    response = await web.client.get(f"{BASE}/documents/{DOC_ID}")

    assert response.status_code == 200
    assert response.json()["route"] == []


async def test_card_not_found_is_404_from_eds(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    eds.error("GET", f"documents/{DOC_ID}", 404, "NOT_FOUND", "Документ не найден.")

    response = await web.client.get(f"{BASE}/documents/{DOC_ID}")

    assert response.status_code == 404
    assert (response.json()["code"], response.json()["source"]) == ("NOT_FOUND", "eds")
    assert (await web.client.get(f"{BASE}/documents/not-a-uuid")).status_code == 422


# --- создание -------------------------------------------------------------------------------------


async def test_create_saves_a_draft(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    await web.login(["MANAGER"])

    response = await web.send("POST", f"{BASE}/documents", json=FORM)

    assert response.status_code == 201, response.text
    check(response, "/eds/documents", "post")
    assert response.json()["status"] == "draft"
    assert eds.body("POST", "documents") == {
        "kind": "memo",
        "subject": FORM["subject"],
        "text": FORM["text"],
        "amount": FORM["amount"],
        "due_date": "2999-11-05",
        "file_ids": [FILE_ID],
        "erp_deal_id": 905,
    }
    assert eds.requests("POST", f"documents/{DOC_ID}/submit") == []
    assert eds.last("POST", "documents").headers["authorization"].startswith(f"Bearer {TOKEN}")


async def test_idempotency_key_goes_to_eds_only_when_given(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    key = "form-key-0001-abcdef"

    keyed = await web.client.post(
        f"{BASE}/documents",
        json=FORM,
        headers={CSRF_HEADER: web.csrf, "Idempotency-Key": key},
    )
    plain = await web.send("POST", f"{BASE}/documents", json=FORM)
    short = await web.client.post(
        f"{BASE}/documents",
        json=FORM,
        headers={CSRF_HEADER: web.csrf, "Idempotency-Key": "short"},
    )

    assert (keyed.status_code, plain.status_code) == (201, 201)
    sent = eds.requests("POST", "documents")
    assert [r.headers.get("idempotency-key") for r in sent] == [key, None]
    assert short.status_code == 422  # ключ короче 8 знаков — до EDS
    assert len(sent) == 2


async def test_create_with_submit_opens_the_route(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])

    response = await web.send("POST", f"{BASE}/documents", json={**FORM, "submit": True})

    assert response.status_code == 201, response.text
    check(response, "/eds/documents", "post")
    body = response.json()
    assert (body["status"], body["can_edit"]) == ("on_approval", False)
    assert [s["label"] for s in body["route"]] == ["Директор", "Бухгалтер"]
    order = [
        (r.method, r.url.path.removeprefix("/api/v1/"))
        for r in eds.calls
        if "documents" in r.url.path
    ]
    assert order == [("POST", "documents"), ("POST", f"documents/{DOC_ID}/submit")]


async def test_create_letter_sends_recipient(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    form = {**FORM, "kind": "letter_out", "recipient": {"name": "ООО «Пример»", "inn": None}}
    form.pop("amount")

    assert (await web.send("POST", f"{BASE}/documents", json=form)).status_code == 201

    assert eds.body("POST", "documents")["recipient"] == {"name": "ООО «Пример»", "inn": None}


async def test_create_submit_rejected_keeps_the_saved_document(web: Web, eds: EdsFake) -> None:
    """
    Документ создан, отправка отклонена: ошибка называет сохранённый черновик — введённое не
    теряется.
    """
    await web.login(["MANAGER"])
    eds.validation("POST", f"documents/{DOC_ID}/submit", addressee_crm_user_id="cannot_approve")

    response = await web.send("POST", f"{BASE}/documents", json={**FORM, "submit": True})

    assert response.status_code == 422
    details = response.json()["details"]
    assert (details["document_id"], details["saved"], details["created"]) == (DOC_ID, True, True)
    assert details["fields"] == ["addressee_crm_user_id"]


async def test_create_validation_is_checked_before_eds(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    cases: list[tuple[dict[str, Any], str]] = [
        ({"subject": "   "}, "subject"),
        ({"text": ""}, "text"),
        ({"text": "  \n "}, "text"),
        ({"amount": {"amount": "0.00", "currency": "UZS"}}, "amount"),
        ({"amount": {"amount": "-5.00", "currency": "UZS"}}, "amount"),
        ({"amount": {"amount": "15", "currency": "UZS"}}, "amount"),
        ({"due_date": "2020-01-01"}, "due_date"),
        ({"kind": "contract"}, "kind"),
        ({"file_ids": ["не-uuid"]}, "file_ids"),
        ({"subject": "x" * 301}, "subject"),
    ]
    for patch, field in cases:
        response = await web.send("POST", f"{BASE}/documents", json={**FORM, **patch})
        assert response.status_code == 422, patch
        body = response.json()
        assert body["code"] == "VALIDATION_FAILED"
        assert any(f.endswith(field) for f in body["details"]["fields"]), (patch, body)
    assert eds.count == 0


async def test_create_translates_eds_errors(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])

    eds.error(
        "POST",
        "documents",
        403,
        "FORBIDDEN",
        "Действие не положено вашей роли.",
        details={"permission": "letters.register"},
    )
    denied = await web.send("POST", f"{BASE}/documents", json={**FORM, "kind": "letter_out"})
    assert denied.status_code == 403
    assert denied.json()["source"] == "eds"
    assert denied.json()["details"]["permission"] == "letters.register"

    eds.validation("POST", "documents", amount="must_be_positive")
    invalid = await web.send("POST", f"{BASE}/documents", json=FORM)
    assert invalid.status_code == 422
    assert invalid.json()["message"] == "Сумма должна быть больше нуля."
    assert invalid.json()["details"]["fields"] == ["amount"]
    assert invalid.json()["details"]["messages"] == {"amount": "must_be_positive"}


# --- сохранение черновика -------------------------------------------------------------------------


async def test_update_saves_the_whole_form_and_clears_empty_fields(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    form = {
        "subject": "Новая тема",
        "text": "Новый текст",
        "amount": None,
        "due_date": None,
        "erp_deal_id": None,
    }

    response = await web.send("PUT", f"{BASE}/documents/{DOC_ID}", json=form)

    assert response.status_code == 200, response.text
    check(response, "/eds/documents/{id}", "put")
    assert response.json()["subject"] == "Новая тема"
    assert eds.body("PATCH", f"documents/{DOC_ID}") == {**form, "file_ids": []}
    assert eds.requests("POST", f"documents/{DOC_ID}/submit") == []


async def test_update_with_submit_sends_for_approval(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])

    # `kind` в форме сохранения не принимается (тип нельзя менять)
    assert (
        await web.send("PUT", f"{BASE}/documents/{DOC_ID}", json={**FORM, "submit": True})
    ).status_code == 422
    form = {k: v for k, v in FORM.items() if k != "kind"}

    response = await web.send("PUT", f"{BASE}/documents/{DOC_ID}", json={**form, "submit": True})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "on_approval"
    order = [
        (r.method, r.url.path.removeprefix("/api/v1/"))
        for r in eds.calls
        if "documents" in r.url.path
    ]
    assert order == [("PATCH", f"documents/{DOC_ID}"), ("POST", f"documents/{DOC_ID}/submit")]


async def test_update_submit_rejected_reports_saved_changes(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    form = {k: v for k, v in FORM.items() if k != "kind"}
    eds.error(
        "POST",
        f"documents/{DOC_ID}/submit",
        409,
        "CONFLICT",
        "Документ нельзя отправить в текущем статусе.",
        details={"reason": "invalid_state", "status": "on_approval"},
    )

    response = await web.send("PUT", f"{BASE}/documents/{DOC_ID}", json={**form, "submit": True})

    assert response.status_code == 409
    details = response.json()["details"]
    assert (details["reason"], details["saved"], details["created"]) == (
        "invalid_state",
        True,
        False,
    )
    assert details["document_id"] == DOC_ID


async def test_update_conflict_and_not_author_pass_through(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    form = {k: v for k, v in FORM.items() if k != "kind"}

    eds.error(
        "PATCH",
        f"documents/{DOC_ID}",
        409,
        "CONFLICT",
        "Документ нельзя править в текущем статусе.",
        details={"reason": "invalid_state"},
    )
    conflict = await web.send("PUT", f"{BASE}/documents/{DOC_ID}", json=form)
    assert (conflict.status_code, conflict.json()["details"]["reason"]) == (409, "invalid_state")

    eds.error(
        "PATCH",
        f"documents/{DOC_ID}",
        403,
        "FORBIDDEN",
        "Править документ может только его автор.",
        details={"reason": "not_author"},
    )
    foreign = await web.send("PUT", f"{BASE}/documents/{DOC_ID}", json=form)
    assert (foreign.status_code, foreign.json()["details"]["reason"]) == (403, "not_author")


# --- вложения -------------------------------------------------------------------------------------


async def test_upload_forwards_multipart_untouched(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    body, content_type = multipart()

    response = await upload(web, body, content_type)

    assert response.status_code == 201, response.text
    check(response, "/eds/document-files", "post")
    assert response.json() == {
        "id": FILE_ID,
        "name": "schet.pdf",
        "content_type": "application/pdf",
        "size": 2048,
    }
    sent = eds.last("POST", "files")
    assert sent.content == body
    assert sent.headers["content-type"] == content_type
    assert sent.headers["authorization"].startswith(f"Bearer {TOKEN}")


async def test_upload_over_limit_is_413_before_eds(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    big = b"x" * (MAX_BODY_BYTES + 1)

    declared = await upload(web, big, f"multipart/form-data; boundary={BOUNDARY}")

    assert declared.status_code == 413
    assert declared.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert declared.json()["details"]["max_bytes"] == MAX_UPLOAD_BYTES
    assert eds.requests("POST", "files") == []


async def test_upload_over_limit_without_content_length_is_413(web: Web, eds: EdsFake) -> None:
    """Загрузка потоком без `Content-Length`: BFF останавливается на первом байте сверх предела."""
    await web.login(["MANAGER"])

    async def chunks() -> Any:
        for _ in range(MAX_BODY_BYTES // (1024 * 1024) + 2):
            yield b"x" * (1024 * 1024)

    response = await web.client.post(
        f"{BASE}/document-files",
        content=chunks(),
        headers={
            "content-type": f"multipart/form-data; boundary={BOUNDARY}",
            CSRF_HEADER: web.csrf,
        },
    )

    assert response.status_code == 413
    assert eds.requests("POST", "files") == []


async def test_upload_requires_multipart(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])

    response = await web.client.post(
        f"{BASE}/document-files",
        content=b"%PDF",
        headers={"content-type": "application/pdf", CSRF_HEADER: web.csrf},
    )

    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "multipart_required"
    assert eds.count == 0


async def test_upload_eds_refusals_are_translated(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    body, content_type = multipart()

    eds.error(
        "POST",
        "files",
        413,
        "PAYLOAD_TOO_LARGE",
        "Файл больше 25 МБ.",
        details={"max_bytes": MAX_UPLOAD_BYTES},
    )
    too_large = await upload(web, body, content_type)
    assert (too_large.status_code, too_large.json()["code"]) == (413, "PAYLOAD_TOO_LARGE")
    assert too_large.json()["details"]["max_bytes"] == MAX_UPLOAD_BYTES

    eds.error(
        "POST",
        "files",
        415,
        "UNSUPPORTED_MEDIA_TYPE",
        "Допустимы PDF, изображения и документы Office.",
    )
    unsupported = await upload(web, body, content_type)
    assert (unsupported.status_code, unsupported.json()["code"]) == (415, "UNSUPPORTED_MEDIA_TYPE")
    assert unsupported.json()["message"] == "Допустимы PDF, изображения и документы Office."


async def test_download_streams_the_file_as_attachment(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])

    response = await web.client.get(f"{BASE}/document-files/{FILE_ID}")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 demo"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''schet.pdf"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert eds.last("GET", f"files/{FILE_ID}").headers["authorization"].startswith("Bearer eds-")


async def test_download_not_found_is_translated(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    eds.error("GET", f"files/{FILE_ID}", 404, "NOT_FOUND", "Файл не найден.")

    response = await web.client.get(f"{BASE}/document-files/{FILE_ID}")

    assert response.status_code == 404
    assert (response.json()["code"], response.json()["source"]) == ("NOT_FOUND", "eds")


# --- связь с проектом -----------------------------------------------------------------------------


DEALS = [
    {
        "id": 904,
        "number": "ЗВ-2026-904",
        "title": "Поставка рельсов Р65",
        "company_name": "ООО «Демо-Путь»",
        "stage_code": "CALCULATING",
        "created_at": "2026-10-01T09:00:00Z",
    },
    {
        "id": 905,
        "number": "ЗВ-2026-905",
        "title": "Монтаж стрелочных переводов",
        "company_name": "АО «Пример-Рельс»",
        "stage_code": "DRAFT",
        "created_at": "2026-10-05T09:00:00Z",
    },
]


def _deals(be: Backends) -> list[httpx.Request]:
    """Сделки ERP; с `?search=` ищет «ERP» (ERP-09): номер, название, компания."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        term = request.url.params.get("search")
        found = [d for d in DEALS if term is None or deal_matches(d, term)]
        return httpx.Response(200, json={"results": found})

    be.router.get(f"{ERP_URL}/api/v1/crm/deals/").mock(side_effect=answer)
    return seen


async def test_deal_options_find_requests_by_number_title_or_company(
    web: Web, be: Backends, eds: EdsFake, check: ContractChecker
) -> None:
    seen = _deals(be)
    await web.login(["MANAGER"])

    everything = await web.client.get(f"{BASE}/deal-options")
    by_number = await web.client.get(f"{BASE}/deal-options?q=zv-2026-905")
    by_title = await web.client.get(f"{BASE}/deal-options?q=рельсов")
    by_company = await web.client.get(f"{BASE}/deal-options?q=пример")

    assert everything.status_code == 200, everything.text
    check(everything, "/eds/deal-options", "get")
    assert [o["erp_deal_id"] for o in everything.json()["items"]] == [905, 904]  # новые выше
    assert everything.json()["sources"]["erp"] == "ok"
    assert [o["erp_deal_id"] for o in by_number.json()["items"]] == [905]
    assert by_number.json()["items"][0]["number"] == "ЗВ-2026-905"
    assert [o["erp_deal_id"] for o in by_title.json()["items"]] == [904]
    assert [o["company"] for o in by_company.json()["items"]] == ["АО «Пример-Рельс»"]
    assert eds.count == 0  # EDS не нужен: сделки — ERP
    # поиск — на стороне ERP: запрос уходит как набран
    assert [r.url.params.get("search") for r in seen] == [None, "zv-2026-905", "рельсов", "пример"]


async def test_deal_options_when_erp_is_down_are_empty_with_source(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    be.router.get(f"{ERP_URL}/api/v1/crm/deals/").mock(return_value=httpx.Response(503))
    await web.login(["MANAGER"])

    response = await web.client.get(f"{BASE}/deal-options?q=ЗВ")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["sources"]["erp"] == "unavailable"


async def test_deal_options_are_closed_to_roles_without_requests_or_projects(
    web: Web, eds: EdsFake
) -> None:
    await web.login(["ADMIN"])  # только `eds.memo.create`: поле «Связь с проектом» не показывается

    response = await web.client.get(f"{BASE}/deal-options")

    assert response.status_code == 403
