"""Логотип контрагента и фото контакта (ЕД-5, СУЩ-3; контракт BFF, тег `chats`).

ERP — на respx; ответы BFF сверяются со схемами platform-bff.yaml. Проверяется то, что делает BFF:
версия превращается в адрес на BFF с `?v=`, адресов хранилища в ответах нет, файл идёт в ERP как
есть, раздел каталога решает доступ до ERP, тело больше предела обрывается, отказы ERP по файлу —
422 с причиной.
"""

from typing import Any

import httpx
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

API = f"{ERP_URL}/api/v1"
CARD = {
    "id": 7,
    "name": "ООО Клиент Юг",
    "inn": "300000555",
    "registration_number": None,
    "country": None,
    "legal_address": None,
    "crm_client_id": None,
    "logo_version": "a1b2c3d4e5",
    "roles": {
        "client": True,
        "supplier": False,
        "manufacturer": False,
        "partner": False,
        "organization": False,
    },
    "people": [
        {
            "id": 31,
            "name": "Анвар Клиентов",
            "position": "Главный инженер",
            "is_primary": True,
            "has_cabinet": False,
            "has_phone": True,
            "has_email": False,
            "photo_version": "f0f0f0f0f0",
        },
        {
            "id": 32,
            "name": "Нилуфар",
            "position": None,
            "is_primary": False,
            "has_cabinet": False,
            "has_phone": False,
            "has_email": True,
            "photo_version": None,
        },
    ],
    "bank_accounts": [],
    "accounts_masked": True,
    "brands": [],
    "do_not_work": None,
}
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 "
FORM = {"file": ("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")}


async def upload(web: Web, url: str, files: dict[str, Any]) -> httpx.Response:
    return await web.client.put(url, files=files, headers={"X-CSRF-Token": web.csrf})


async def test_card_turns_versions_into_bff_addresses_only(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/organizations/7/").mock(return_value=httpx.Response(200, json=CARD))
    response = await web.client.get("/api/v1/people/counterparties/7")
    assert response.status_code == 200, response.text
    check(response, "/people/counterparties/{id}", "get")
    body = response.json()
    assert body["logo_url"] == "/api/v1/people/counterparties/7/logo?v=a1b2c3d4e5"
    first, second = body["people"]
    assert first["photo_url"] == "/api/v1/people/contacts/31/photo?v=f0f0f0f0f0"
    assert second["photo_url"] is None
    # версии и адресов хранилища в ответе нет
    assert "logo_version" not in body
    assert "photo_version" not in first
    assert "/media/" not in response.text


async def test_logo_is_streamed_from_erp_as_webp(web: Web, be: Any) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    route = router.get(f"{API}/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(200, content=WEBP, headers={"content-type": "image/webp"})
    )
    response = await web.client.get(
        "/api/v1/people/counterparties/7/logo", params={"v": "a1", "size": "full"}
    )
    assert response.status_code == 200
    assert response.content == WEBP
    assert response.headers["content-type"] == "image/webp"
    assert "max-age=86400" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert dict(route.calls.last.request.url.params) == {"size": "full"}


async def test_no_logo_is_404(web: Web, be: Any) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    assert (await web.client.get("/api/v1/people/counterparties/7/logo")).status_code == 404
    # ERP ответил не картинкой — тоже «нет логотипа», а не страница с чужим типом
    router.get(f"{API}/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
    )
    assert (await web.client.get("/api/v1/people/counterparties/7/logo")).status_code == 404


async def test_upload_passes_the_form_to_erp_and_returns_the_card(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    route = router.put(f"{API}/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(200, json=CARD)
    )
    response = await upload(web, "/api/v1/people/counterparties/7/logo", FORM)
    assert response.status_code == 200, response.text
    check(response, "/people/counterparties/{id}/logo", "put")
    assert response.json()["logo_url"].endswith("?v=a1b2c3d4e5")
    sent = route.calls.last.request
    assert sent.headers["content-type"].startswith("multipart/form-data")
    assert b"0" * 32 in sent.content


async def test_upload_refusals_of_erp_are_422_with_the_reason(web: Web, be: Any) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    router.put(f"{API}/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(400, json={"detail": "FILE_TYPE_NOT_ALLOWED"})
    )
    response = await upload(web, "/api/v1/people/counterparties/7/logo", FORM)
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "file_type_not_allowed"
    router.put(f"{API}/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(403, json={"detail": "ROLE_NOT_PERMITTED"})
    )
    assert (await upload(web, "/api/v1/people/counterparties/7/logo", FORM)).status_code == 403


async def test_upload_must_be_multipart_and_is_cut_at_the_limit(web: Web, be: Any) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    route = router.put(f"{API}/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(200, json=CARD)
    )
    plain = await web.send("PUT", "/api/v1/people/counterparties/7/logo", json={"a": 1})
    assert plain.status_code == 422
    assert plain.json()["details"]["reason"] == "multipart_required"
    big = {"file": ("logo.png", b"0" * (2 * 1024 * 1024 + 300 * 1024), "image/png")}
    response = await upload(web, "/api/v1/people/counterparties/7/logo", big)
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert not route.called  # ERP тяжёлое тело не получил


async def test_section_decides_before_erp(web: Web, be: Any) -> None:
    await web.login(["ACCOUNTANT"])  # бухгалтер видит контрагентов, но не правит их
    router: respx.MockRouter = be.router
    route = router.put(f"{API}/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(200, json=CARD)
    )
    response = await upload(web, "/api/v1/people/counterparties/7/logo", FORM)
    assert response.status_code == 403
    assert not route.called
    delete = await web.send("DELETE", "/api/v1/people/counterparties/7/logo")
    assert delete.status_code == 403
    assert not route.called


async def test_contact_photo_roundtrip(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    router.put(f"{API}/parties/people/31/photo/").mock(
        return_value=httpx.Response(200, json={"id": 31, "photo_version": "0a0a0a0a0a"})
    )
    response = await upload(web, "/api/v1/people/contacts/31/photo", FORM)
    assert response.status_code == 200, response.text
    check(response, "/people/contacts/{id}/photo", "put")
    assert response.json() == {
        "id": "31",
        "photo_url": "/api/v1/people/contacts/31/photo?v=0a0a0a0a0a",
    }
    router.delete(f"{API}/parties/people/31/photo/").mock(
        return_value=httpx.Response(200, json={"id": 31, "photo_version": None})
    )
    removed = await web.send("DELETE", "/api/v1/people/contacts/31/photo")
    assert removed.json() == {"id": "31", "photo_url": None}
    router.get(f"{API}/parties/people/31/photo/").mock(
        return_value=httpx.Response(200, content=WEBP, headers={"content-type": "image/webp"})
    )
    served = await web.client.get("/api/v1/people/contacts/31/photo", params={"v": "x"})
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"


async def test_people_list_carries_the_photo_address(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.get(f"{API}/parties/people/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "id": 31,
                        "name": "Анвар",
                        "position": None,
                        "has_email": False,
                        "has_phone": False,
                        "is_primary": True,
                        "company": {"id": 7, "name": "ООО Клиент Юг"},
                        "kind": "client",
                        "photo_version": "f0f0f0f0f0",
                    }
                ],
            },
        )
    )
    response = await web.client.get("/api/v1/people/contacts")
    check(response, "/people/contacts", "get")
    assert (
        response.json()["items"][0]["photo_url"] == "/api/v1/people/contacts/31/photo?v=f0f0f0f0f0"
    )
