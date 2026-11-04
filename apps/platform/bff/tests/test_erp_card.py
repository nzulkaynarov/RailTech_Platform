"""Карточка товара в Платформе (CAT-CARD-1): фото, документы с видом из справочника, страна.

ERP — на respx. Проверяется: раздел `erp.stock` (чтение и изменения), загрузка фото (multipart
как есть, предел 5 МБ), отказы ERP по полю `image`, файл фото только через BFF и только по
пути этой позиции, паспорт документа, новые поля карточки."""

import json
from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.test_erp_catalog import ITEM_DETAIL

API = f"{ERP_URL}/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
IMAGE = {
    "id": 8,
    "url": "/media/products/4/images/a.png",
    "is_main": True,
    "sort_order": 0,
    "alt": "Вид",
}
CARD = {**ITEM_DETAIL, "offers": [], "images": [IMAGE]}


def multipart(data: bytes = PNG, name: str = "a.png") -> tuple[bytes, str]:
    boundary = "bndry9"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="alt_text"\r\n\r\nВид\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
        "Content-Type: image/png\r\n\r\n".encode()
        + data
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def headers(web: Web, content_type: str = "application/json") -> dict[str, str]:
    return {"content-type": content_type, "X-CSRF-Token": web.csrf}


# --- карточка ---------------------------------------------------------------------------------


async def test_card_carries_photos_documents_origin_and_warranty(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    be.router.get(f"{API}/catalog/items/4/").mock(return_value=httpx.Response(200, json=CARD))

    response = await web.client.get("/api/v1/erp/catalog/items/4")

    assert response.status_code == 200
    check(response, "/erp/catalog/items/{id}", "get")
    body = response.json()
    assert body["images"] == [
        {"id": "8", "is_main": True, "sort_order": 0, "alt": "Вид"}
    ]  # адрес хранилища наружу не идёт
    assert body["origin"] == {
        "own": None,
        "effective": {"id": "3", "name": "Узбекистан"},
        "brand": {"id": "3", "name": "Узбекистан"},
        "source": "brand",
    }
    assert body["warranty"] == {
        "months": None,
        "terms": "",
        "effective_months": 12,
        "company_months": 12,
        "source": "company",
    }
    doc = body["tech_docs"][0]
    assert (doc["kind"], doc["kind_name"], doc["number"], doc["client_visible"]) == (
        "certificate",
        "Сертификат соответствия",
        "RU-1",
        True,
    )


async def test_country_and_warranty_go_to_erp_with_numeric_country(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    route = be.router.patch(f"{API}/catalog/items/4/").mock(
        return_value=httpx.Response(200, json=CARD)
    )

    response = await web.client.patch(
        "/api/v1/erp/catalog/items/4",
        content=json.dumps(
            {
                "country_of_origin_id": "3",
                "warranty_months": 24,
                "warranty_terms": "Замена при браке",
            }
        ),
        headers=headers(web),
    )

    assert response.status_code == 200
    check(response, "/erp/catalog/items/{id}", "patch")
    assert json.loads(route.calls.last.request.content) == {
        "country_of_origin_id": 3,
        "warranty_months": 24,
        "warranty_terms": "Замена при браке",
    }
    cleared = await web.client.patch(
        "/api/v1/erp/catalog/items/4",
        content=json.dumps({"country_of_origin_id": None, "warranty_months": None}),
        headers=headers(web),
    )
    assert cleared.status_code == 200
    assert json.loads(route.calls.last.request.content) == {
        "country_of_origin_id": None,
        "warranty_months": None,
    }
    too_long = await web.client.patch(
        "/api/v1/erp/catalog/items/4",
        content=json.dumps({"warranty_months": 601}),
        headers=headers(web),
    )
    assert too_long.status_code == 422


# --- фото -------------------------------------------------------------------------------------


async def test_photo_upload_goes_to_erp_as_is(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    route = be.router.post(f"{API}/catalog/items/4/images/").mock(
        return_value=httpx.Response(201, json=IMAGE)
    )
    body, content_type = multipart()

    response = await web.client.post(
        "/api/v1/erp/catalog/items/4/images", content=body, headers=headers(web, content_type)
    )

    assert response.status_code == 201, response.text
    check(response, "/erp/catalog/items/{id}/images", "post")
    assert response.json() == {"id": "8", "is_main": True, "sort_order": 0, "alt": "Вид"}
    assert route.calls.last.request.content == body
    assert route.calls.last.request.headers["content-type"] == content_type


async def test_photo_upload_needs_multipart_and_has_a_five_megabyte_limit(
    web: Web, be: Backends
) -> None:
    await web.login(["ENGINEER"])
    route = be.router.post(f"{API}/catalog/items/4/images/").mock(
        return_value=httpx.Response(201, json=IMAGE)
    )

    plain = await web.client.post(
        "/api/v1/erp/catalog/items/4/images", content=b"{}", headers=headers(web)
    )
    assert plain.status_code == 422
    assert plain.json()["details"]["fields"] == ["image"]

    big, content_type = multipart(data=b"0" * (6 * 1024 * 1024))
    too_large = await web.client.post(
        "/api/v1/erp/catalog/items/4/images", content=big, headers=headers(web, content_type)
    )
    assert too_large.status_code == 413
    assert too_large.json()["details"]["max_bytes"] == 5 * 1024 * 1024
    assert route.call_count == 0


@pytest.mark.parametrize(
    ("detail", "field"),
    [
        ("FILE_TOO_LARGE", "image"),
        ("FILE_TYPE_NOT_ALLOWED", "image"),
        ("FILE_CONTENT_MISMATCH", "image"),
        ("NO_FILE_PROVIDED", "image"),
        ("IMAGE_LIMIT_REACHED", "image"),
    ],
)
async def test_erp_photo_refusals_name_the_image_field(
    web: Web, be: Backends, detail: str, field: str
) -> None:
    await web.login(["ENGINEER"])
    be.router.post(f"{API}/catalog/items/4/images/").mock(
        return_value=httpx.Response(400, json={"detail": detail})
    )
    body, content_type = multipart()

    response = await web.client.post(
        "/api/v1/erp/catalog/items/4/images", content=body, headers=headers(web, content_type)
    )

    assert response.status_code == 422
    assert response.json()["details"]["fields"] == [field]
    assert response.json()["details"]["reason"] == detail.lower()


async def test_photo_main_order_and_alt_are_forwarded_and_delete_returns_no_content(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    patch = be.router.patch(f"{API}/catalog/items/4/images/8/").mock(
        return_value=httpx.Response(200, json=IMAGE)
    )
    delete = be.router.delete(f"{API}/catalog/items/4/images/8/").mock(
        return_value=httpx.Response(204)
    )

    for sent in ({"is_main": True}, {"sort_order": 2}, {"alt_text": "Сбоку"}):
        response = await web.client.patch(
            "/api/v1/erp/catalog/items/4/images/8", content=json.dumps(sent), headers=headers(web)
        )
        assert response.status_code == 200
        check(response, "/erp/catalog/items/{id}/images/{image_id}", "patch")
        assert json.loads(patch.calls.last.request.content) == sent
    for bad in ({"is_main": False}, {"sort_order": -1}, {}):
        response = await web.client.patch(
            "/api/v1/erp/catalog/items/4/images/8", content=json.dumps(bad), headers=headers(web)
        )
        assert response.status_code == 422, bad
    removed = await web.client.delete(
        "/api/v1/erp/catalog/items/4/images/8", headers={"X-CSRF-Token": web.csrf}
    )
    assert removed.status_code == 204
    assert delete.call_count == 1


async def test_photo_file_comes_through_bff_from_the_path_in_the_card(
    web: Web, be: Backends
) -> None:
    await web.login(["MANAGER"])
    be.router.get(f"{API}/catalog/items/4/").mock(return_value=httpx.Response(200, json=CARD))
    file = be.router.get(f"{ERP_URL}/media/products/4/images/a.png").mock(
        return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    )

    response = await web.client.get("/api/v1/erp/catalog/items/4/images/8/content")

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert file.call_count == 1


@pytest.mark.parametrize(
    ("url", "content_type"),
    [
        ("/media/products/5/images/a.png", "image/png"),  # чужая позиция
        ("/media/companies/1/logo/a.png", "image/png"),  # не фото товара
        ("/media/products/4/images/../../x.png", "image/png"),
        ("/media/products/4/images/a.svg", "image/svg+xml"),  # не растр
        ("/media/products/4/images/a.png", "text/html"),
    ],
)
async def test_photo_file_outside_the_item_or_not_a_raster_is_not_found(
    web: Web, be: Backends, url: str, content_type: str
) -> None:
    await web.login(["MANAGER"])
    card = {**CARD, "images": [{**IMAGE, "url": url}]}
    be.router.get(f"{API}/catalog/items/4/").mock(return_value=httpx.Response(200, json=card))
    file = be.router.route(path__startswith="/media/").mock(
        return_value=httpx.Response(200, content=b"x", headers={"content-type": content_type})
    )

    response = await web.client.get("/api/v1/erp/catalog/items/4/images/8/content")

    assert response.status_code == 404
    if not url.startswith("/media/products/4/images/a."):
        assert file.call_count == 0


async def test_photo_that_is_not_in_the_card_is_not_found_and_nothing_is_fetched(
    web: Web, be: Backends
) -> None:
    await web.login(["MANAGER"])
    be.router.get(f"{API}/catalog/items/4/").mock(return_value=httpx.Response(200, json=CARD))
    file = be.router.route(path__startswith="/media/").mock(
        return_value=httpx.Response(200, content=b"x")
    )

    response = await web.client.get("/api/v1/erp/catalog/items/4/images/99/content")

    assert response.status_code == 404
    assert file.call_count == 0


# --- документы --------------------------------------------------------------------------------

DOC: dict[str, Any] = {
    "id": 5,
    "kind": "certificate",
    "kind_name": "Сертификат соответствия",
    "title": "Сертификат на реле",
    "number": "RU-0042",
    "issued_by": "Орган по сертификации",
    "issued_at": "2026-01-10",
    "valid_until": "2027-01-10",
    "is_expired": False,
    "client_visible": True,
    "original_name": "cert.pdf",
    "content_type": "application/pdf",
    "size_bytes": 10,
    "previewable": True,
    "product": {"id": 4, "name": "Реле", "sku": "RT-1"},
    "deal": None,
    "uploaded_by": "Снабженец",
    "created_at": "2026-11-04T09:00:00Z",
}


async def test_document_passport_fields_are_returned_and_edited(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    be.router.get(f"{API}/catalog/tech-docs/").mock(
        return_value=httpx.Response(
            200, json={"count": 1, "next": None, "previous": None, "results": [DOC]}
        )
    )
    patch = be.router.patch(f"{API}/catalog/tech-docs/5/").mock(
        return_value=httpx.Response(200, json=DOC)
    )

    listed = await web.client.get("/api/v1/erp/docs/files", params={"kind": "certificate"})
    assert listed.status_code == 200
    check(listed, "/erp/docs/files", "get")
    row = listed.json()["items"][0]
    assert (row["kind_name"], row["number"], row["valid_until"], row["client_visible"]) == (
        "Сертификат соответствия",
        "RU-0042",
        "2027-01-10",
        True,
    )

    sent = {"number": "RU-0043", "valid_until": None, "client_visible": False}
    edited = await web.client.patch(
        "/api/v1/erp/docs/files/5", content=json.dumps(sent), headers=headers(web)
    )
    assert edited.status_code == 200
    check(edited, "/erp/docs/files/{id}", "patch")
    assert json.loads(patch.calls.last.request.content) == sent
    bad_date = await web.client.patch(
        "/api/v1/erp/docs/files/5",
        content=json.dumps({"valid_until": "31.12.2027"}),
        headers=headers(web),
    )
    assert bad_date.status_code == 422


@pytest.mark.parametrize(
    ("detail", "field"),
    [
        ("TECH_DOC_KIND_INVALID", "kind"),
        ("TECH_DOC_DATE_INVALID", "valid_until"),
        ("TECH_DOC_VALIDITY_RANGE_INVALID", "valid_until"),
    ],
)
async def test_document_passport_refusals_name_the_field(
    web: Web, be: Backends, detail: str, field: str
) -> None:
    await web.login(["ENGINEER"])
    be.router.patch(f"{API}/catalog/tech-docs/5/").mock(
        return_value=httpx.Response(400, json={"detail": detail})
    )

    response = await web.client.patch(
        "/api/v1/erp/docs/files/5", content=json.dumps({"number": "X"}), headers=headers(web)
    )

    assert response.status_code == 422
    assert response.json()["details"]["fields"] == [field]
