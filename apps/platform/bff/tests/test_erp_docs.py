"""Расчёт · Техдокументация (контракт BFF 0.26.0, тег `erp-catalog`; D2-3, B-019 часть «ERP ·
Документация»).

ERP — на respx. Проверяется: раздел `erp.stock` (чтение и изменения), загрузка (multipart уходит в
ERP как есть, предел 20 МБ, не multipart — 422), выдача файла (всегда вложением, `nosniff`,
поток), привязка к заявке с номером ЗВ/ПР."""

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

API = f"{ERP_URL}/api/v1"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
DOC = {
    "id": 5,
    "kind": "tz",
    "title": "ТЗ на реле",
    "original_name": "tz.pdf",
    "content_type": "application/pdf",
    "size_bytes": len(PDF),
    "previewable": True,
    "product": {"id": 4, "name": "Реле защиты РЗ-1", "sku": "RT-0002"},
    "deal": {
        "id": 905,
        "title": "Монтаж",
        "client": "АО «Пример-Рельс»",
        "stage_code": "DRAFT",
        "created_at": "2026-10-05T09:00:00Z",
    },
    "uploaded_by": "Гл. инженер",
    "created_at": "2026-10-28T09:00:00Z",
}


def multipart(file_name: str = "tz.pdf", data: bytes = PDF) -> tuple[bytes, str]:
    boundary = "bndry7"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="product_id"\r\n\r\n4\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        "Content-Type: application/pdf\r\n\r\n".encode()
        + data
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def headers(web: Web, content_type: str) -> dict[str, str]:
    return {"content-type": content_type, "X-CSRF-Token": web.csrf}


async def test_list_forwards_filters_and_numbers_the_deal(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    route = be.router.get(f"{API}/catalog/tech-docs/").mock(
        return_value=httpx.Response(
            200, json={"count": 1, "next": None, "previous": None, "results": [DOC]}
        )
    )

    response = await web.client.get(
        "/api/v1/erp/docs/files",
        params={"q": "реле", "kind": "tz", "product_id": "4", "deal_id": "905", "page_size": 50},
    )

    assert response.status_code == 200
    check(response, "/erp/docs/files", "get")
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["deal"]["number"] == "ЗВ-2026-905"
    assert body["items"][0]["product"] == {"id": "4", "name": "Реле защиты РЗ-1", "sku": "RT-0002"}
    assert dict(route.calls.last.request.url.params) == {
        "q": "реле",
        "kind": "tz",
        "product": "4",
        "deal": "905",
        "page": "1",
        "page_size": "50",
    }


async def test_bad_filters_are_refused_before_erp(web: Web, be: Backends) -> None:
    await web.login(["MANAGER"])
    assert (await web.client.get("/api/v1/erp/docs/files?kind=poster")).status_code == 422
    assert (await web.client.get("/api/v1/erp/docs/files?product_id=x")).status_code == 422
    assert (await web.client.get("/api/v1/erp/docs/files/abc/content")).status_code == 422


async def test_upload_goes_to_erp_as_is_and_returns_the_card(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    route = be.router.post(f"{API}/catalog/tech-docs/").mock(
        return_value=httpx.Response(201, json=DOC)
    )
    body, content_type = multipart()

    response = await web.client.post(
        "/api/v1/erp/docs/files", content=body, headers=headers(web, content_type)
    )

    assert response.status_code == 201, response.text
    check(response, "/erp/docs/files", "post")
    assert route.calls.last.request.content == body
    assert route.calls.last.request.headers["content-type"] == content_type
    assert route.calls.last.request.headers["authorization"].startswith("Bearer ")


async def test_upload_needs_multipart_and_has_a_size_limit(web: Web, be: Backends) -> None:
    await web.login(["ENGINEER"])
    route = be.router.post(f"{API}/catalog/tech-docs/").mock(
        return_value=httpx.Response(201, json=DOC)
    )

    plain = await web.client.post(
        "/api/v1/erp/docs/files", content=b"{}", headers=headers(web, "application/json")
    )
    assert plain.status_code == 422
    assert plain.json()["details"]["reason"] == "multipart_required"

    big, content_type = multipart(data=b"0" * (21 * 1024 * 1024 + 10))
    too_large = await web.client.post(
        "/api/v1/erp/docs/files", content=big, headers=headers(web, content_type)
    )
    assert too_large.status_code == 413
    assert too_large.json()["details"]["max_bytes"] == 20 * 1024 * 1024
    assert route.call_count == 0


@pytest.mark.parametrize(
    ("detail", "field"),
    [
        ("FILE_TOO_LARGE", "file"),
        ("FILE_TYPE_NOT_ALLOWED", "file"),
        ("FILE_CONTENT_MISMATCH", "file"),
        ("TECH_DOC_LINK_REQUIRED", "product_id"),
    ],
)
async def test_erp_upload_refusals_name_the_field(
    web: Web, be: Backends, detail: str, field: str
) -> None:
    await web.login(["ENGINEER"])
    be.router.post(f"{API}/catalog/tech-docs/").mock(
        return_value=httpx.Response(400, json={"detail": detail})
    )
    body, content_type = multipart()

    response = await web.client.post(
        "/api/v1/erp/docs/files", content=body, headers=headers(web, content_type)
    )

    assert response.status_code == 422
    assert response.json()["details"]["fields"] == [field]
    assert response.json()["details"]["reason"] == detail.lower()


async def test_download_is_always_an_attachment_with_nosniff(web: Web, be: Backends) -> None:
    await web.login(["MANAGER"])
    route = be.router.get(f"{API}/catalog/tech-docs/5/file/").mock(
        return_value=httpx.Response(
            200,
            content=PDF,
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'inline; filename="tz.pdf"',
            },
        )
    )

    response = await web.client.get("/api/v1/erp/docs/files/5/content")

    assert response.status_code == 200
    assert response.content == PDF
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"] == 'attachment; filename="tz.pdf"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert dict(route.calls.last.request.url.params) == {"download": "1"}


async def test_download_of_a_missing_file_is_not_found(web: Web, be: Backends) -> None:
    await web.login(["MANAGER"])
    be.router.get(f"{API}/catalog/tech-docs/9/file/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    response = await web.client.get("/api/v1/erp/docs/files/9/content")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_delete_is_for_full_access_and_returns_no_content(web: Web, be: Backends) -> None:
    await web.login(["SUPPLY"])
    route = be.router.delete(f"{API}/catalog/tech-docs/5/").mock(return_value=httpx.Response(204))
    response = await web.client.delete(
        "/api/v1/erp/docs/files/5", headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 204
    assert route.call_count == 1

    be.router.delete(f"{API}/catalog/tech-docs/6/").mock(
        return_value=httpx.Response(403, json={"detail": "ROLE_NOT_PERMITTED"})
    )
    refused = await web.client.delete(
        "/api/v1/erp/docs/files/6", headers={"X-CSRF-Token": web.csrf}
    )
    assert refused.status_code == 403
    assert refused.json()["source"] == "erp"


async def test_deal_options_find_a_project_by_number(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.router.get(f"{API}/crm/deals/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 905,
                        "title": "Монтаж",
                        "company_name": "АО «Пример-Рельс»",
                        "stage_code": "DRAFT",
                        "created_at": "2026-10-05T09:00:00Z",
                    }
                ]
            },
        )
    )
    await web.login(["ENGINEER"])

    response = await web.client.get("/api/v1/erp/docs/deals", params={"q": "zv-2026-905"})

    assert response.status_code == 200, response.text
    check(response, "/erp/docs/deals", "get")
    assert response.json()["items"][0]["number"] == "ЗВ-2026-905"


async def test_accountant_reads_but_cannot_upload(web: Web, be: Backends) -> None:
    await web.login(["ACCOUNTANT"])
    body, content_type = multipart()
    response = await web.client.post(
        "/api/v1/erp/docs/files", content=body, headers=headers(web, content_type)
    )
    assert response.status_code == 403
    assert response.json()["details"] == {"resource": "erp.stock", "need": "full"}
